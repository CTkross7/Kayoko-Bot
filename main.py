# main.py
# ──────────────────────────────────────────────────────────
# 카요코 봇 리워크 — 엔트리포인트
# ──────────────────────────────────────────────────────────

import asyncio
import traceback

import discord
from discord import app_commands, Embed, Interaction
from discord.ext import commands, tasks
from kayoko_ai import KayokoPipeline


# main.py 상단 import 부분에 추가
from utils.dishost_api import post_server_count

from config import (
    BOT_TOKEN, GOOGLE_API_KEYS, GEMINI_MODEL_NAME,
    GUILD_ID, DEVELOPER_ID, COLOR_ERROR,
    KAYOKO_SETTINGS_FILE, KAYOKO_USAGE_FILE,
    KST,DISHOST_STATS_INTERVAL
)
from models.cat import load_cats
from data_manager import load_json

# ═══════════════════════════════════════════════════════════
# 봇 인스턴스 생성
# ═══════════════════════════════════════════════════════════

intents = discord.Intents.all()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ── 디스호스트 자동 서버 수 전송 태스크 ──
@tasks.loop(seconds=DISHOST_STATS_INTERVAL)
async def dishost_stats_loop():
    """1시간마다 디스호스트에 서버 수 전송"""
    if bot.is_ready():
        await post_server_count(len(bot.guilds))

@dishost_stats_loop.before_loop
async def before_dishost_stats():
    await bot.wait_until_ready()

# ═══════════════════════════════════════════════════════════
# ★ 밴 체크 통합 헬퍼
# ═══════════════════════════════════════════════════════════

def _check_all_bans(user_id: int) -> tuple[bool, dict | None]:
    from utils.checks import is_banned
    banned, ban_info = is_banned(user_id)
    if banned:
        return True, ban_info

    try:
        from systems.anticheat import is_auto_banned
        if is_auto_banned(user_id):
            return True, {
                "reason": "안티치트 시스템에 의한 자동 차단",
                "banned_by": "AntiCheat System",
                "expire_at": 0,
            }
    except ImportError:
        pass

    return False, None


def _build_ban_embed(ban_info: dict) -> Embed:
    from datetime import datetime, timezone

    embed = Embed(
        title="🚫 접근 차단됨",
        description="이 계정은 현재 차단 상태입니다.\n모든 봇 기능 사용이 제한됩니다.",
        color=COLOR_ERROR,
    )
    embed.add_field(name="사유", value=ban_info.get("reason", "사유 없음"), inline=False)

    expire_at = ban_info.get("expire_at")
    if expire_at == 0 or expire_at is None:
        embed.add_field(name="기간", value="영구 차단", inline=True)
    else:
        try:
            expire_time = datetime.fromtimestamp(expire_at, tz=timezone.utc)
            embed.add_field(name="만료", value=expire_time.strftime("%Y-%m-%d %H:%M UTC"), inline=True)
        except (ValueError, TypeError, OSError):
            embed.add_field(name="기간", value="영구 차단", inline=True)

    embed.set_footer(text="문의: 공식 서버에서 관리자에게 연락해주세요.")
    return embed


# ═══════════════════════════════════════════════════════════
# ★ 글로벌 슬래시 커맨드 밴 체크
# ═══════════════════════════════════════════════════════════


@bot.tree.interaction_check
async def global_checks(interaction: discord.Interaction) -> bool:
    # 1. 기존 밴 체크 (이미 차단된 유저인지 확인)
    banned, ban_info = _check_all_bans(interaction.user.id)
    if banned:
        embed = _build_ban_embed(ban_info)
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)
        return False

    # 2. ★ 실시간 안티치트 검사 추가
    # 매 커맨드 실행 시마다 빈도를 계산하고 비정상 패턴을 탐지합니다.
    try:
        from systems.anticheat import run_anticheat_checks
        passed, anti_reason = await run_anticheat_checks(
            user_id=interaction.user.id,
            username=interaction.user.display_name,
            interaction=interaction,
            check_type="command"
        )
        if not passed:
            # run_anticheat_checks 내부에서 이미 경고 메시지 송출 및 밴 처리가 이루어집니다.
            return False
    except ImportError:
        # 파일 경로가 다르거나 파일이 없을 경우를 대비한 안전장치
        print("[오류] anticheat 시스템을 로드할 수 없습니다.")

    # 3. 서버 봇 비활성화 체크
    if interaction.guild:
        from data_manager import load_guild_config
        config = load_guild_config(interaction.guild.id)
        if not config.get("bot_enabled", True):
            # 서버 설정 커맨드는 예외
            cmd_name = interaction.command.name if interaction.command else ""
            admin_cmds = {"서버설정", "봇토글", "공지채널설정", "공지채널삭제"}
            if cmd_name not in admin_cmds:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ 이 서버에서 봇이 비활성화 상태입니다.\n서버 관리자가 `/봇토글`로 활성화할 수 있습니다.",
                        ephemeral=True,
                    )
                return False

    return True

# ═══════════════════════════════════════════════════════════
# Gemini AI (카요코 대화) — ★ API 키 자동 검증 + 자동 로테이션
# ═══════════════════════════════════════════════════════════

import google.generativeai as genai
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# ── API 키 리스트 (config.py에서 가져오거나 여기에 직접 정의) ──
try:
    from config import GOOGLE_API_KEYS
except ImportError:
    GOOGLE_API_KEYS = [GOOGLE_API_KEY] if GOOGLE_API_KEY else []

if not GOOGLE_API_KEYS:
    GOOGLE_API_KEYS = [GOOGLE_API_KEY]


class GeminiKeyRotator:
    """
    Gemini API 키를 자동으로 로테이션하는 매니저.

    ★ v2 변경점:
    - 초기화 시 모든 키를 비동기로 검증하여 활성 키만 사용
    - generate_response 호출 시 현재 키를 사전 검증(pre-flight check)
    - 비활성 키 자동 제외 및 주기적 재검증 지원
    - 에러 발생 시 다음 활성 키로 자동 전환
    - 모든 키가 실패하면 쿨다운 후 재시도
    - 서버 재시작 없이 실시간 적용
    """

    def __init__(self, api_keys: list[str], model_name: str):
        self.api_keys = list(api_keys)
        self.model_name = model_name
        self.current_index = 0
        self.total_keys = len(self.api_keys)

        # ★ 키별 활성 상태 (초기화 검증 전까지는 None = 미확인)
        # True = 활성, False = 비활성(검증 실패), None = 미확인
        self.key_active: dict[int, bool | None] = {i: None for i in range(self.total_keys)}

        # ★ 키별 마지막 검증 시각 (timestamp)
        self.last_validated: dict[int, float] = {i: 0.0 for i in range(self.total_keys)}

        # ★ 검증 재시도 간격 (비활성 키를 다시 검증해보는 주기, 초)
        self.revalidation_interval = 600  # 10분

        # 키별 실패 카운트 및 쿨다운
        self.fail_counts: dict[int, int] = {i: 0 for i in range(self.total_keys)}
        self.cooldown_until: dict[int, float] = {i: 0.0 for i in range(self.total_keys)}

        # 연속 전체 실패 시 글로벌 쿨다운 (초)
        self.global_cooldown_seconds = 60
        self.global_cooldown_until = 0.0

        # 키별 최대 연속 실패 허용 (이후 해당 키 쿨다운)
        self.max_fails_per_key = 3
        self.key_cooldown_seconds = 120  # 개별 키 쿨다운 2분

        # 현재 활성 모델 & 채팅 세션
        self._model = None
        self._chat = None
        self._active_key_index = -1

        # ★ 초기화는 동기로 첫 번째 키만 설정 (비동기 검증은 startup에서 수행)
        self._initialize_current_key()

        print(f"[Gemini] API 키 {self.total_keys}개 등록 완료 (현재: #{self.current_index + 1})")

    # ─────────────────────────────────────────────────────
    # ★ 키 유효성 검증 (단일 키)
    # ─────────────────────────────────────────────────────

    def _validate_key_sync(self, key_index: int) -> bool:
        """
        특정 인덱스의 API 키가 유효한지 동기적으로 검증합니다.
        간단한 API 호출(모델 목록 조회)을 시도하여 키 상태를 확인합니다.

        반환: True = 활성, False = 비활성/오류
        """
        key = self.api_keys[key_index]
        try:
            genai.configure(api_key=key)
            # 가벼운 API 호출로 키 유효성 확인
            # list_models()는 할당량을 거의 소모하지 않음
            models = list(genai.list_models())
            if models:
                self.key_active[key_index] = True
                self.last_validated[key_index] = datetime.now().timestamp()
                return True
            else:
                # 모델 목록이 비어있는 경우 (비정상)
                self.key_active[key_index] = False
                self.last_validated[key_index] = datetime.now().timestamp()
                return False
        except Exception as e:
            error_str = str(e).lower()
            # API 키 자체가 잘못된 경우
            is_invalid_key = any(kw in error_str for kw in [
                "api_key_invalid", "invalid api key", "permission_denied",
                "api key not valid", "forbidden", "401", "403",
            ])
            if is_invalid_key:
                self.key_active[key_index] = False
                print(f"[Gemini] 키 #{key_index + 1} 검증 실패 (무효한 키): {str(e)[:80]}")
            else:
                # 일시적 네트워크 오류 등은 활성으로 간주 (나중에 재시도)
                self.key_active[key_index] = True
                print(f"[Gemini] 키 #{key_index + 1} 검증 중 일시 오류 (활성 유지): {str(e)[:80]}")
            self.last_validated[key_index] = datetime.now().timestamp()
            return self.key_active[key_index]

    async def _validate_key_async(self, key_index: int) -> bool:
        """
        특정 인덱스의 API 키를 비동기적으로 검증합니다.
        블로킹 호출을 asyncio.to_thread로 래핑합니다.
        """
        return await asyncio.to_thread(self._validate_key_sync, key_index)

    # ─────────────────────────────────────────────────────
    # ★ 전체 키 초기 검증 (봇 시작 시 호출)
    # ─────────────────────────────────────────────────────

    async def validate_all_keys(self):
        """
        모든 API 키를 비동기로 검증합니다.
        봇의 on_ready 또는 setup_hook에서 호출하세요.
        검증 후 첫 번째 활성 키로 자동 전환합니다.
        """
        print(f"[Gemini] 전체 API 키 검증 시작 ({self.total_keys}개)...")

        tasks_list = []
        for i in range(self.total_keys):
            tasks_list.append(self._validate_key_async(i))

        results = await asyncio.gather(*tasks_list, return_exceptions=True)

        active_count = 0
        inactive_indices = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.key_active[i] = False
                inactive_indices.append(i)
                print(f"[Gemini] 키 #{i + 1} 검증 예외: {result}")
            elif result:
                active_count += 1
            else:
                inactive_indices.append(i)

        print(
            f"[Gemini] 키 검증 완료: "
            f"{active_count}/{self.total_keys}개 활성"
        )

        if inactive_indices:
            inactive_str = ", ".join(f"#{i + 1}" for i in inactive_indices)
            print(f"[Gemini] 비활성 키: {inactive_str}")

        # 첫 번째 활성 키로 전환
        if active_count > 0:
            first_active = self._find_first_active_key()
            if first_active is not None and first_active != self.current_index:
                self.current_index = first_active
                self._initialize_current_key()
                print(f"[Gemini] 첫 번째 활성 키로 전환: #{first_active + 1}")
            elif first_active is not None:
                # 현재 키가 이미 활성이면 재초기화만
                self._initialize_current_key()
        else:
            print("[Gemini] ⚠️ 경고: 활성 API 키가 하나도 없습니다!")

    def _find_first_active_key(self) -> int | None:
        """활성 상태인 첫 번째 키의 인덱스를 반환합니다."""
        for i in range(self.total_keys):
            if self.key_active.get(i) is True:
                return i
        return None

    # ─────────────────────────────────────────────────────
    # ★ 비활성 키 주기적 재검증
    # ─────────────────────────────────────────────────────

    async def revalidate_inactive_keys(self):
        """
        비활성으로 표시된 키 중 revalidation_interval이 지난 키를 재검증합니다.
        tasks.loop 등에서 주기적으로 호출할 수 있습니다.
        """
        now = datetime.now().timestamp()
        revalidated = 0

        for i in range(self.total_keys):
            if self.key_active.get(i) is False:
                last_check = self.last_validated.get(i, 0)
                if now - last_check >= self.revalidation_interval:
                    result = await self._validate_key_async(i)
                    revalidated += 1
                    if result:
                        print(f"[Gemini] 키 #{i + 1} 재검증 성공 → 활성으로 복구")
                        # 쿨다운도 해제
                        self.cooldown_until[i] = 0.0
                        self.fail_counts[i] = 0

        if revalidated > 0:
            print(f"[Gemini] 비활성 키 {revalidated}개 재검증 완료")

    # ─────────────────────────────────────────────────────
    # 키 초기화 및 로테이션 (기존 + 검증 통합)
    # ─────────────────────────────────────────────────────

    def _initialize_current_key(self):
        """현재 인덱스의 키로 모델을 초기화합니다."""
        key = self.api_keys[self.current_index]
        genai.configure(api_key=key)

        settings = load_json(KAYOKO_SETTINGS_FILE, {})
        system_prompt = settings.get("system_instruction", "")

        self._model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system_prompt,
        )
        self._chat = self._model.start_chat(history=[])
        self._active_key_index = self.current_index

        # 해당 키의 실패 카운트 리셋
        self.fail_counts[self.current_index] = 0

    def _rotate_to_next_key(self) -> bool:
        """
        다음 사용 가능한 키로 전환합니다.

        ★ v2: 비활성(key_active=False) 키와 쿨다운 중인 키를 모두 건너뜁니다.

        반환: 사용 가능한 키를 찾았으면 True, 모든 키가 사용 불가면 False
        """
        now = datetime.now().timestamp()
        start_index = self.current_index

        for _ in range(self.total_keys):
            self.current_index = (self.current_index + 1) % self.total_keys

            # ★ 비활성 키는 건너뜀
            if self.key_active.get(self.current_index) is False:
                continue

            # 쿨다운 중인 키는 건너뜀
            if self.cooldown_until.get(self.current_index, 0) > now:
                continue

            # 사용 가능한 키 발견
            old_index = self._active_key_index
            self._initialize_current_key()
            print(
                f"[Gemini] API 키 로테이션: #{old_index + 1} → #{self.current_index + 1} "
                f"(총 {self.total_keys}개 중, 활성: {self._count_active_keys()}개)"
            )
            return True

        # 모든 키가 사용 불가
        return False

    def _count_active_keys(self) -> int:
        """현재 활성 상태인 키의 수를 반환합니다."""
        now = datetime.now().timestamp()
        count = 0
        for i in range(self.total_keys):
            if self.key_active.get(i) is not False:
                if self.cooldown_until.get(i, 0) <= now:
                    count += 1
        return count

    def _handle_api_error(self, error: Exception):
        """API 에러 발생 시 키 상태를 업데이트합니다."""
        idx = self.current_index
        self.fail_counts[idx] = self.fail_counts.get(idx, 0) + 1

        error_str = str(error).lower()

        # ★ API 키 자체가 무효한 에러인지 판별
        is_invalid_key = any(keyword in error_str for keyword in [
            "api_key_invalid", "invalid api key", "permission_denied",
            "api key not valid", "forbidden", "401", "403",
        ])

        if is_invalid_key:
            # ★ 무효한 키 → 비활성으로 영구 표시 (재검증 시까지)
            self.key_active[idx] = False
            self.last_validated[idx] = datetime.now().timestamp()
            print(
                f"[Gemini] 키 #{idx + 1} 무효 → 비활성 처리 "
                f"({self.revalidation_interval}초 후 재검증 예정)"
            )
            return

        # 할당량/한도 초과 에러인지 판별
        is_quota_error = any(keyword in error_str for keyword in [
            "quota", "rate_limit", "resource_exhausted",
            "429", "too many requests", "limit exceeded",
            "resourceexhausted", "quota_exceeded",
        ])

        if is_quota_error:
            # 할당량 초과 → 해당 키를 즉시 쿨다운
            now = datetime.now().timestamp()
            self.cooldown_until[idx] = now + self.key_cooldown_seconds
            self.fail_counts[idx] = self.max_fails_per_key  # 즉시 최대 실패 처리
            print(
                f"[Gemini] 키 #{idx + 1} 할당량 초과 → "
                f"{self.key_cooldown_seconds}초 쿨다운 적용"
            )
        elif self.fail_counts[idx] >= self.max_fails_per_key:
            # 일반 에러 연속 N회 → 쿨다운
            now = datetime.now().timestamp()
            self.cooldown_until[idx] = now + self.key_cooldown_seconds
            print(
                f"[Gemini] 키 #{idx + 1} 연속 {self.fail_counts[idx]}회 실패 → "
                f"{self.key_cooldown_seconds}초 쿨다운 적용"
            )

    # ─────────────────────────────────────────────────────
    # ★ 사전 검증 (Pre-flight Check)
    # ─────────────────────────────────────────────────────

    async def _ensure_active_key(self) -> bool:
        """
        현재 키가 활성 상태인지 확인하고, 아니면 활성 키로 로테이션합니다.
        미확인(None) 상태의 키는 즉석 검증을 수행합니다.

        반환: 사용 가능한 키가 있으면 True, 없으면 False
        """
        now = datetime.now().timestamp()

        # 글로벌 쿨다운 체크
        if self.global_cooldown_until > now:
            remaining = int(self.global_cooldown_until - now)
            print(f"[Gemini] 글로벌 쿨다운 중 ({remaining}초 남음)")
            return False

        current_status = self.key_active.get(self.current_index)

        # Case 1: 현재 키가 비활성으로 확인됨
        if current_status is False:
            print(f"[Gemini] 현재 키 #{self.current_index + 1}은 비활성 → 로테이션 시도")
            if not self._rotate_to_next_key():
                # 모든 키 사용 불가 → 비활성 키 재검증 시도
                print("[Gemini] 모든 키 사용 불가 → 비활성 키 긴급 재검증 시도")
                await self.revalidate_inactive_keys()
                # 재검증 후 다시 로테이션 시도
                if not self._rotate_to_next_key():
                    self.global_cooldown_until = now + self.global_cooldown_seconds
                    print(
                        f"[Gemini] 재검증 후에도 사용 가능한 키 없음 → "
                        f"{self.global_cooldown_seconds}초 글로벌 대기"
                    )
                    return False
            return True

        # Case 2: 현재 키가 미확인(None) → 즉석 검증
        if current_status is None:
            print(f"[Gemini] 키 #{self.current_index + 1} 미확인 → 즉석 검증 수행")
            is_valid = await self._validate_key_async(self.current_index)
            if not is_valid:
                print(f"[Gemini] 키 #{self.current_index + 1} 즉석 검증 실패 → 로테이션 시도")
                if not self._rotate_to_next_key():
                    self.global_cooldown_until = now + self.global_cooldown_seconds
                    return False
            else:
                # 검증 성공 → 모델 재초기화 (검증 과정에서 genai.configure가 바뀌었을 수 있으므로)
                self._initialize_current_key()
            return True

        # Case 3: 현재 키가 활성(True)이지만 쿨다운 중
        if self.cooldown_until.get(self.current_index, 0) > now:
            print(f"[Gemini] 현재 키 #{self.current_index + 1}은 쿨다운 중 → 로테이션 시도")
            if not self._rotate_to_next_key():
                self.global_cooldown_until = now + self.global_cooldown_seconds
                print(
                    f"[Gemini] 모든 활성 키 쿨다운 → "
                    f"{self.global_cooldown_seconds}초 글로벌 대기"
                )
                return False
            return True

        # Case 4: 현재 키가 활성이고 쿨다운도 아님 → 사용 가능
        return True

    # ─────────────────────────────────────────────────────
    # 응답 생성 (★ 사전 검증 통합)
    # ─────────────────────────────────────────────────────

    async def generate_response(self, user_message: str) -> str | None:
        """
        메시지를 Gemini에 전송합니다.

        ★ v2 변경점:
        1. 호출 전 _ensure_active_key()로 현재 키 사전 검증
        2. 실패 시 비활성 키를 자동 제외하고 다음 활성 키로 로테이션
        3. 무효 키 에러(401/403) 발생 시 해당 키를 영구 비활성 처리
        """
        now = datetime.now().timestamp()

        # ★ Step 1: 사전 검증 — 활성 키 확보
        has_active_key = await self._ensure_active_key()
        if not has_active_key:
            print("[Gemini] 사용 가능한 API 키가 없습니다.")
            return None

        # ★ Step 2: 활성 키만 대상으로 시도 (최대 활성 키 수만큼)
        max_attempts = self._count_active_keys()
        if max_attempts == 0:
            print("[Gemini] 활성 키가 0개입니다.")
            return None

        attempts = 0
        last_error = None

        while attempts < max_attempts:
            try:
                # 모델이 현재 키와 일치하는지 확인
                if self._active_key_index != self.current_index:
                    self._initialize_current_key()

                response = await asyncio.to_thread(
                    self._chat.send_message, user_message
                )

                # 성공 → 실패 카운트 리셋
                self.fail_counts[self.current_index] = 0
                return response.text

            except Exception as e:
                last_error = e
                error_name = type(e).__name__
                print(
                    f"[Gemini] 키 #{self.current_index + 1} 에러: "
                    f"{error_name} — {str(e)[:100]}"
                )

                self._handle_api_error(e)

                # 다음 활성 키로 로테이션 시도
                if self._rotate_to_next_key():
                    attempts += 1
                    continue
                else:
                    # 모든 키 실패
                    self.global_cooldown_until = now + self.global_cooldown_seconds
                    print(
                        f"[Gemini] 모든 API 키 소진 → "
                        f"{self.global_cooldown_seconds}초 글로벌 대기"
                    )
                    break

        # 모든 시도 실패
        if last_error:
            traceback.print_exception(type(last_error), last_error, last_error.__traceback__)
        return None

    # ─────────────────────────────────────────────────────
    # 상태 조회 (★ 활성/비활성 상태 추가)
    # ─────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """현재 로테이터 상태를 반환합니다. (디버깅/관리자용)"""
        now = datetime.now().timestamp()
        keys_status = []
        for i in range(self.total_keys):
            cd_remaining = max(0, self.cooldown_until.get(i, 0) - now)
            active_status = self.key_active.get(i)
            if active_status is True:
                status_label = "✅ 활성"
            elif active_status is False:
                status_label = "❌ 비활성"
            else:
                status_label = "❓ 미확인"

            last_val = self.last_validated.get(i, 0)
            if last_val > 0:
                validated_ago = round(now - last_val, 1)
                validated_str = f"{validated_ago}초 전"
            else:
                validated_str = "미검증"

            keys_status.append({
                "index": i + 1,
                "active": i == self.current_index,
                "status": status_label,
                "key_valid": active_status,
                "fails": self.fail_counts.get(i, 0),
                "cooldown_remaining": round(cd_remaining, 1),
                "last_validated": validated_str,
                "key_preview": self.api_keys[i][:8] + "..." if self.api_keys[i] else "N/A",
            })

        global_cd = max(0, self.global_cooldown_until - now)
        active_count = sum(1 for i in range(self.total_keys) if self.key_active.get(i) is True)
        usable_count = self._count_active_keys()

        return {
            "total_keys": self.total_keys,
            "active_keys": active_count,
            "usable_keys": usable_count,
            "current_key": self.current_index + 1,
            "global_cooldown_remaining": round(global_cd, 1),
            "revalidation_interval": self.revalidation_interval,
            "keys": keys_status,
        }


# ── 인스턴스 생성 ──

gemini_rotator = GeminiKeyRotator(
    api_keys=GOOGLE_API_KEYS,
    model_name=GEMINI_MODEL_NAME,
)


class KayokoUsageManager:
    """유저별 AI 대화 사용량 관리"""

    def __init__(self):
        self.usage_data = load_json(KAYOKO_USAGE_FILE, {})
        settings = load_json(KAYOKO_SETTINGS_FILE, {})
        self.max_daily = settings.get("max_daily_usage", 50)
        self.max_per_minute = 2
        self.cooldown_seconds = 60

    def check_can_chat(self, user_id: int) -> tuple:
        uid = str(user_id)
        kst = ZoneInfo("Asia/Seoul")
        now = datetime.now(timezone.utc).astimezone(kst)
        today = now.strftime("%Y-%m-%d")
        current_ts = datetime.now().timestamp()

        if uid not in self.usage_data:
            self.usage_data[uid] = {
                "count": 0,
                "last_date": today,
                "minute_timestamps": [],
            }

        info = self.usage_data[uid]

        if info.get("last_date") != today:
            info["count"] = 0
            info["last_date"] = today
            info["minute_timestamps"] = []
            self._save()

        info["minute_timestamps"] = [
            ts for ts in info.get("minute_timestamps", [])
            if ts > current_ts - self.cooldown_seconds
        ]

        if len(info["minute_timestamps"]) >= self.max_per_minute:
            self._save()
            return False, "...너무 빨라, 선생님. 잠시만 기다려."

        if info["count"] >= self.max_daily:
            self._save()
            return False, "...미안하지만 오늘은 너무 많이 대화했어. 내일 다시 이야기하자."

        self._save()
        return True, None

    def increment(self, user_id: int):
        uid = str(user_id)
        if uid in self.usage_data:
            self.usage_data[uid]["count"] += 1
            self.usage_data[uid].setdefault("minute_timestamps", []).append(
                datetime.now().timestamp()
            )
            self._save()

    def _save(self):
        from data_manager import save_json
        save_json(KAYOKO_USAGE_FILE, self.usage_data)


usage_manager = KayokoUsageManager()

kayoko_pipeline = KayokoPipeline(
    bot=bot,
    gemini_rotator=gemini_rotator,
    usage_manager=usage_manager,
    ban_checker=_check_all_bans,
)

# ── Gemini 비활성 키 주기적 재검증 태스크 ──
@tasks.loop(minutes=10)
async def gemini_revalidation_loop():
    """10분마다 비활성 API 키를 재검증하여 복구된 키를 자동 활성화"""
    try:
        await gemini_rotator.revalidate_inactive_keys()
    except Exception as e:
        print(f"[Gemini] 재검증 루프 오류: {e}")

@gemini_revalidation_loop.before_loop
async def before_gemini_revalidation():
    await bot.wait_until_ready()

# ═══════════════════════════════════════════════════════════
# 이벤트 핸들러
# ═══════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    cats = load_cats()
    print(f"[데이터] 냥이 {len(cats)}종 로드 완료")

    activity = discord.Game(name="고양이 납치")
    await bot.change_presence(status=discord.Status.online, activity=activity)

    # ★ Gemini API 키 전체 검증 (봇 시작 시)
    await gemini_rotator.validate_all_keys()
    
    # ★ 카요코 AI 파이프라인 시작 (지식베이스 색인)
    await kayoko_pipeline.startup()
    
    cog_modules = [
        "commands.general",
        "commands.gameplay",
        "commands.admin",
        "commands.battle_commands",
        "commands.labyrinth_commands",
        "commands.shop_commands",
        "commands.verification",
        "commands.welcome",
        "commands.notice",
        "commands.gambling_commands",
        "commands.server_settings",
        "commands.vote_commands",
        "commands.enhancement_commands",

    ]
    for cog in cog_modules:
        try:
            await bot.load_extension(cog)
            print(f"[Cog] {cog} 로드 완료")
        except Exception as e:
            print(f"[Cog] {cog} 로드 실패: {e}")
            traceback.print_exc()

    try:
        synced = await bot.tree.sync()
        print(f"[명령어] {len(synced)}개 싱크 완료")
    except Exception as e:
        print(f"[명령어] 싱크 실패: {e}")

    # 디스호스트 통계 루프 시작
    if not dishost_stats_loop.is_running():
        dishost_stats_loop.start()

    # ★ 비활성 키 주기적 재검증 루프 시작
    if not gemini_revalidation_loop.is_running():
        gemini_revalidation_loop.start()

    # 초기 서버 수 전송
    await post_server_count(len(bot.guilds))
    
    print(f"[봇] {bot.user} 로그인 완료")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
        
    content = message.content.strip()
    
    handled = await kayoko_pipeline.handle_message(message)
    if handled:
        return

        # 종합 밴 체크
        banned, ban_info = _check_all_bans(message.author.id)
        if banned:
            embed = _build_ban_embed(ban_info)
            await message.reply(embed=embed)
            return

    await bot.process_commands(message)

# ── 서버 입퇴장 시 즉시 갱신 ──
@bot.event
async def on_guild_join(guild):
    print(f"[서버] 참가: {guild.name} ({guild.id})")
    await post_server_count(len(bot.guilds))

@bot.event
async def on_guild_remove(guild):
    print(f"[서버] 퇴장: {guild.name} ({guild.id})")
    await post_server_count(len(bot.guilds))

# ═══════════════════════════════════════════════════════════
# 에러 핸들러
# ═══════════════════════════════════════════════════════════

@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    command_name = interaction.command.name if interaction.command else "???"

    if isinstance(error, app_commands.CheckFailure):
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ 이 커맨드를 사용할 수 없습니다.", ephemeral=True)
        return

    if isinstance(error, app_commands.CommandInvokeError):
        original = error.original
        print(f"\n--- [커맨드 에러] /{command_name} ---")
        traceback.print_exception(type(original), original, original.__traceback__)

        msg = f"❌ 커맨드 실행 중 오류가 발생했습니다. (`/{command_name}`)"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    else:
        print(f"[알 수 없는 에러] /{command_name}: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        if not interaction.response.is_done():
            await interaction.response.send_message(f"⚠️ 오류: `{error}`", ephemeral=True)


# ═══════════════════════════════════════════════════════════
# 봇 실행
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    bot.run(BOT_TOKEN)
