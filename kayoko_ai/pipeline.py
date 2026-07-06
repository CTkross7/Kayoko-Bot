# kayoko_ai/pipeline.py
"""
카요코 AI 통합 파이프라인.

main.py의 on_message에서:
    await kayoko_pipeline.handle_message(message)
한 줄로 처리됩니다.

흐름:
  1. 트리거 판정 (직접/엠비언트)
  2. 사용량/밴 체크
  3. 컨텍스트 조립
     - 단기기억 (최근 10개)
     - 장기기억 회상 (RAG)
     - 지식베이스 회상 (RAG)
     - 집단기억 (채널 최근 10개)
  4. Gemini 호출 (키 로테이션)
  5. 다이나믹 펄스 전송
  6. 단기기억 갱신 + 10회마다 장기기억 형성
"""

from __future__ import annotations

import asyncio
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
import google.generativeai as genai

from config import (
    GEMINI_MODEL_NAME,
    KAYOKO_SETTINGS_FILE,
    LONG_TERM_FORM_EVERY,
)
from data_manager import load_json
from kayoko_ai.embedding import EmbeddingClient
from kayoko_ai.knowledge_base import KnowledgeBase
from kayoko_ai.memory import NeuralCore
from kayoko_ai.flow import (
    SessionManager,
    AdaptiveReflex,
    detect_trigger,
    is_ambient_trigger,
)
from kayoko_ai.pulse import send_with_pulse


# ─────────────────────────────────────────────────────
# 프롬프트 빌더
# ─────────────────────────────────────────────────────

def build_prompt(
    system_instruction: str,
    user_name: str,
    query: str,
    short_term: list[dict],
    long_term_hits: list[dict],
    knowledge_hits: list[dict],
    ambient_hits: list[dict],
) -> tuple[str, str]:
    """
    Gemini 호출용 (system_instruction, user_message) 튜플 반환.
    system_instruction은 캐릭터 페르소나 + 동적 컨텍스트.
    user_message는 실제 사용자 발화.
    """
    kst = ZoneInfo("Asia/Seoul")
    now = datetime.now(kst).strftime("%Y-%m-%d %H:%M (KST)")

    sys_parts: list[str] = [system_instruction.strip(), ""]

    # 현재 시간
    sys_parts.append(f"[현재 시각] {now}")
    sys_parts.append("")

    # 지식베이스 회상
    if knowledge_hits:
        sys_parts.append("[참고할 블루 아카이브 설정]")
        for h in knowledge_hits:
            text = h.get("text") if isinstance(h, dict) else str(h)
            sys_parts.append(f"- {text}")
        sys_parts.append("")

    # 장기기억 회상
    if long_term_hits:
        sys_parts.append(f"[{user_name}에 대해 떠오르는 기억]")
        for h in long_term_hits:
            text = h.get("text") if isinstance(h, dict) else str(h)
            sys_parts.append(f"- {text}")
        sys_parts.append("")

    # 집단기억
    if ambient_hits:
        sys_parts.append("[방금 채널에서 오간 대화]")
        for m in ambient_hits[-6:]:
            author = m.get("author", "누군가") if isinstance(m, dict) else "누군가"
            text = m.get("text", "") if isinstance(m, dict) else str(m)
            sys_parts.append(f"- {author}: {text}")
        sys_parts.append("")

    # 단기기억
    if short_term:
        sys_parts.append("[직전 대화 흐름]")
        for m in short_term:
            role = "선생님" if m.get("role") == "user" else "나"
            text = m.get("text", "")
            sys_parts.append(f"{role}: {text}")
        sys_parts.append("")

    sys_parts.append(
        "위 맥락을 자연스럽게 활용해 카요코로서 답해. "
        "맥락에 없는 사실은 추측하지 말고, "
        "카요코다운 말투 — 무뚝뚝하고 차분하며 가끔 한숨 — 을 유지해."
    )

    full_system = "\n".join(sys_parts)
    return full_system, query


# ─────────────────────────────────────────────────────
# 파이프라인
# ─────────────────────────────────────────────────────

class KayokoPipeline:
    def __init__(self, bot, gemini_rotator, usage_manager, ban_checker):
        """
        bot: discord.Client/Bot
        gemini_rotator: main.py의 GeminiKeyRotator 인스턴스
        usage_manager: main.py의 KayokoUsageManager 인스턴스
        ban_checker: (user_id) -> (bool, dict|None)
        """

        # GeminiKeyRotator 클래스 자체가 들어오는 실수 방지
        if isinstance(gemini_rotator, type):
            raise TypeError(
                "gemini_rotator에는 GeminiKeyRotator 클래스가 아니라 "
                "GeminiKeyRotator(...)로 생성한 인스턴스를 넣어야 합니다."
            )

        self.bot = bot
        self.rotator = gemini_rotator
        self.usage = usage_manager
        self.ban_check = ban_checker

        self.embed = EmbeddingClient(gemini_rotator)
        self.kb = KnowledgeBase(self.embed)
        self.core = NeuralCore(self.embed)
        self.sessions = SessionManager()
        self._summary_lock = asyncio.Lock()

        # ── AI 대화 반응 쿨타임
        # usage_manager의 일일/분당 사용량 제한과 별개입니다.
        self._last_direct_response_at: dict[int, float] = {}
        self._last_ambient_response_at: dict[int, float] = {}
        self._last_channel_ambient_at: dict[int, float] = {}

        # 직접 호출은 짧게 제한
        self.direct_user_cooldown = 3

        # 엠비언트는 보수적으로 제한
        self.ambient_user_cooldown = 12
        self.channel_ambient_cooldown = 8

    async def startup(self):
        """봇 시작 시 호출 — 지식베이스 색인."""
        await self.kb.build_index()

    # ─────────────────────────────────────────────
    # 메인 진입점
    # ─────────────────────────────────────────────

    async def handle_message(self, message: discord.Message) -> bool:
        """
        반환:
          True  = 이 메시지를 카요코가 처리했거나 처리 시도함
          False = 일반 명령어 등 외부 처리로 넘김
        """
        if message.author.bot or not message.guild:
            return False

        # ── 집단 기억 수집
        # 트리거 여부와 무관하게 일반 유저 메시지는 채널 분위기로 저장
        try:
            self.core.ambient.add(
                channel_id=message.channel.id,
                author=message.author.display_name,
                text=(message.content or "")[:500],
            )
        except Exception:
            pass

        bot_id = self.bot.user.id if self.bot.user else 0
        session = self.sessions.get(message.author.id, message.channel.id)

        # ── 트리거 판정 ──
        direct, query = detect_trigger(message, bot_id)

        if direct:
            # 직접 호출만 세션을 엽니다.
            session.touch()
        else:
            # 엠비언트 플로우는 flow.py에서 매우 보수적으로 판정합니다.
            if not is_ambient_trigger(message, session, bot_id):
                return False

            query = (message.content or "").strip()
            if not query:
                return False

        # 직접 호출했지만 내용이 비어 있는 경우
        if not query:
            try:
                await message.reply("...왜 불렀어? 용건만 말해, 귀찮으니까.")
            except Exception:
                pass
            return True

        # ── 밴 체크 ──
        banned, ban_info = self.ban_check(message.author.id)
        if banned:
            from main import _build_ban_embed  # 순환 임포트 회피
            try:
                await message.reply(embed=_build_ban_embed(ban_info))
            except Exception:
                pass
            return True

        # ── 사용량 체크 ──
        can_chat, limit_msg = self.usage.check_can_chat(message.author.id)
        if not can_chat:
            try:
                await message.reply(limit_msg)
            except Exception:
                pass
            return True

        # ── 어댑티브 리플렉스
        # 직접 호출일 때만 기존 응답을 끊습니다.
        # 엠비언트 메시지로 기존 응답이 계속 취소되는 현상을 막습니다.
        if direct:
            await AdaptiveReflex.interrupt(session)

        # ── 자연 대화용 쿨타임
        now_ts = datetime.now().timestamp()

        if direct:
            last_direct = self._last_direct_response_at.get(message.author.id, 0)
            if now_ts - last_direct < self.direct_user_cooldown:
                return True

            self._last_direct_response_at[message.author.id] = now_ts

        else:
            last_ambient_user = self._last_ambient_response_at.get(message.author.id, 0)
            if now_ts - last_ambient_user < self.ambient_user_cooldown:
                return False

            last_ambient_channel = self._last_channel_ambient_at.get(message.channel.id, 0)
            if now_ts - last_ambient_channel < self.channel_ambient_cooldown:
                return False

            self._last_ambient_response_at[message.author.id] = now_ts
            self._last_channel_ambient_at[message.channel.id] = now_ts

        # ── 응답 태스크 시작 ──
        task = asyncio.create_task(self._respond(message, session, query, direct))
        AdaptiveReflex.attach(session, task)
        return True

    # ─────────────────────────────────────────────
    # 실제 응답 생성
    # ─────────────────────────────────────────────

    async def _respond(
        self,
        message: discord.Message,
        session,
        query: str,
        direct: bool,
    ):
        try:
            # 1. 페르소나 로드
            settings = load_json(KAYOKO_SETTINGS_FILE, {})
            persona = settings.get("system_instruction", "")

            # 2. 컨텍스트 회상
            short_term = self.core.short.get_recent(message.author.id)

            long_recall_task = self.core.long.recall(message.author.id, query)
            kb_task = self.kb.search(query)

            long_hits, kb_hits = await asyncio.gather(
                long_recall_task,
                kb_task,
                return_exceptions=False,
            )

            ambient = self.core.ambient.get(message.channel.id)

            # 3. 프롬프트 조립
            full_system, user_msg = build_prompt(
                system_instruction=persona,
                user_name=message.author.display_name,
                query=query,
                short_term=short_term,
                long_term_hits=long_hits,
                knowledge_hits=kb_hits,
                ambient_hits=ambient,
            )

            # 4. Gemini 호출
            response_text = await self._generate(full_system, user_msg)
            if not response_text:
                err = settings.get("error_messages", {}).get(
                    "general_error",
                    "...에러가 발생했어. 나중에 다시 말해줘.",
                )
                await message.reply(err)
                return

            # 5. 다이나믹 펄스 전송
            sent_msgs = await send_with_pulse(
                channel=message.channel,
                full_text=response_text.strip(),
                reply_to=message,
            )

            # 6. 세션/기억 업데이트
            # 직접 호출만 세션을 연장합니다.
            # 엠비언트 응답으로 session.touch()를 계속 호출하면
            # 세션이 무한 연장되어 모든 일반 채팅에 반응하는 문제가 생깁니다.
            if direct:
                session.touch()

            if sent_msgs:
                last_msg_id = sent_msgs[-1].id

                if hasattr(session, "mark_bot_reply"):
                    session.mark_bot_reply(last_msg_id)
                else:
                    session.last_bot_message_id = last_msg_id

            self.usage.increment(message.author.id)

            self.core.short.append(message.author.id, "user", query)
            self.core.short.append(message.author.id, "model", response_text)
            await self.core.persist()

            # 7. 장기기억 형성
            if self.core.should_form_long_term(message.author.id):
                asyncio.create_task(self._form_long_term(message.author.id))

        except asyncio.CancelledError:
            print(f"[Reflex] 응답 취소됨 (user={message.author.id})")
            raise

        except Exception:
            traceback.print_exc()
            try:
                settings = load_json(KAYOKO_SETTINGS_FILE, {})
                err = settings.get("error_messages", {}).get(
                    "general_error",
                    "...에러가 발생했어.",
                )
                await message.reply(err)
            except Exception:
                pass

    # ─────────────────────────────────────────────
    # Gemini 호출
    # ─────────────────────────────────────────────

    async def _generate(self, system_instruction: str, user_message: str) -> str | None:
        """
        매 호출마다 system_instruction이 동적으로 바뀌므로
        GenerativeModel을 새로 만들어 사용.
        키 로테이션은 rotator를 통해 처리.
        """

        ok = await self.rotator._ensure_active_key()
        if not ok:
            return None

        max_attempts = self.rotator._count_active_keys() or 1
        last_err = None

        for _ in range(max_attempts):
            try:
                key = self.rotator.api_keys[self.rotator.current_index]
                genai.configure(api_key=key)

                def _call():
                    model = genai.GenerativeModel(
                        model_name=GEMINI_MODEL_NAME,
                        system_instruction=system_instruction,
                    )
                    return model.generate_content(user_message)

                response = await asyncio.to_thread(_call)

                self.rotator.fail_counts[self.rotator.current_index] = 0

                text = getattr(response, "text", None)
                if not text:
                    return None

                return text

            except asyncio.CancelledError:
                raise

            except Exception as e:
                last_err = e
                print(
                    f"[Pipeline] 생성 실패 "
                    f"(키 #{self.rotator.current_index + 1}): {e}"
                )

                self.rotator._handle_api_error(e)

                if not self.rotator._rotate_to_next_key():
                    break

        if last_err:
            traceback.print_exception(
                type(last_err),
                last_err,
                last_err.__traceback__,
            )

        return None

    # ─────────────────────────────────────────────
    # 장기기억 형성
    # ─────────────────────────────────────────────

    async def _form_long_term(self, user_id: int):
        """
        최근 N개 대화를 요약 → 장기기억으로 저장.
        Gemini로 요약하여 중요 정보를 추출.
        """
        async with self._summary_lock:
            try:
                msgs = self.core.short.get_recent(
                    user_id,
                    n=LONG_TERM_FORM_EVERY * 2,
                )

                if len(msgs) < 4:
                    return

                convo_text = "\n".join(
                    f"{'선생님' if m.get('role') == 'user' else '카요코'}: {m.get('text', '')}"
                    for m in msgs
                )

                summarize_prompt = (
                    "다음은 한 사용자와 카요코의 대화입니다. "
                    "사용자에 대해 새로 알게 된 사실"
                    "(이름/취미/직업/약속/관계/감정/선호 등)이 있다면 "
                    "한 문장씩 간결한 한국어 요약 bullet로 정리하세요. "
                    "추측하지 말고, 대화에 명시된 사실만 적으세요. "
                    "새로 알게 된 것이 없으면 '없음'이라고만 답하세요.\n\n"
                    f"{convo_text}"
                )

                summary = await self._generate(
                    system_instruction="당신은 사실 추출 요약기입니다.",
                    user_message=summarize_prompt,
                )

                if not summary or "없음" in summary[:10]:
                    return

                added = 0

                for line in summary.splitlines():
                    line = line.strip().lstrip("-•*0123456789. )").strip()

                    if len(line) < 5:
                        continue

                    if await self.core.long.add_episode(user_id, line):
                        added += 1

                if added:
                    print(f"[NeuralCore] 장기기억 {added}개 추가 (user={user_id})")

            except Exception:
                traceback.print_exc()