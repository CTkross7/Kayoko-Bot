# config.py
# ──────────────────────────────────────────────────────────
# 카요코 봇 리워크 - 전역 설정 및 상수 (밸런스 v2)
# ──────────────────────────────────────────────────────────

import os
from zoneinfo import ZoneInfo

# 로컬 개발 편의를 위해 .env 파일이 있으면 자동 로드합니다.
# (python-dotenv 미설치 시 조용히 무시 — 배포 환경에서는 보통
#  플랫폼이 환경변수를 직접 주입하므로 필요 없습니다.)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# config.py 기존 내용 끝에 추가

# ═══════════════════════════════════════════════════════════
# 카요코 AI (뉴럴 코어 / 엠비언트 플로우) 설정
# ═══════════════════════════════════════════════════════════

# ── 임베딩 모델 ──
# Gemini API 무료 티어에서 사용 가능 (768차원)
# https://ai.google.dev/gemini-api/docs/embeddings
EMBEDDING_MODEL = "models/text-embedding-004"
EMBEDDING_DIM = 768

# ── 트리거 ──
KAYOKO_TRIGGERS = ("카요코쨩", "카요코짱", "카요코쩡")

# ── 엠비언트 플로우 ──
AMBIENT_SESSION_TIMEOUT = 300  # 5분 (초)

# ── 뉴럴 코어 ──
SHORT_TERM_MAX = 30          # 유저별 단기 기억 최대 개수
SHORT_TERM_INJECT = 10       # 프롬프트에 주입할 최근 대화 수
LONG_TERM_FORM_EVERY = 10    # 대화 N회마다 장기기억 형성
LONG_TERM_RECALL_TOP_K = 3   # 회상할 장기기억 개수
LONG_TERM_DEDUP_THRESHOLD = 0.85  # 중복 판정 코사인 유사도
LONG_TERM_RECALL_MIN_SIM = 0.55   # 회상 최소 유사도
AMBIENT_CONTEXT_MAX = 10     # 집단 기억(채널 최근 대화)

# ── 지식베이스 (RAG) ──
KNOWLEDGE_RECALL_TOP_K = 5
KNOWLEDGE_MIN_SIM = 0.50

# ── 다이나믹 펄스 ──
PULSE_CHARS_PER_SEC = 18      # 평균 타이핑 속도 (한글 기준)
PULSE_MIN_DELAY = 0.6
PULSE_MAX_DELAY = 2.8
PULSE_SPLIT_MAX_LEN = 80      # 메시지 청크 최대 길이(문자)

# ── 어댑티브 리플렉스 ──
REFLEX_INTERRUPT_GRACE = 0.15  # 새 메시지 감지 후 취소 유예(초)

# ── 데이터 파일 ──
KNOWLEDGE_FILE = "data/kayoko_knowledge.json"
SHORT_TERM_FILE = "data/memory/short_term.json"
LONG_TERM_FILE = "data/memory/long_term.json"
AMBIENT_FILE = "data/memory/ambient_context.json"
SESSION_FILE = "data/sessions.json"

# 메모리 디렉토리 자동 생성
os.makedirs("data/memory", exist_ok=True)

# ═══════════════════════════════════════════════════════════
# 봇 기본 설정
# ═══════════════════════════════════════════════════════════
# 시크릿은 코드에 하드코딩하지 않고 환경변수에서 읽습니다.
# 로컬 개발 시 .env 파일을 만들어 사용하세요 (.env.example 참고).
TestBuild = os.getenv("DISCORD_TEST_TOKEN", "")
KayokoToken = os.getenv("DISCORD_BOT_TOKEN", "")

# BOT_ENV=test 이면 TestBuild, 그 외(prod 등)면 KayokoToken 사용
# BOT_TOKEN을 직접 지정하면 그 값이 우선됩니다.
BOT_TOKEN = os.getenv("BOT_TOKEN") or (
    TestBuild if os.getenv("BOT_ENV", "test") == "test" else KayokoToken
)

# Gemini API 키 리스트 (로테이션용)
# 한도 초과 시 자동으로 다음 키로 전환됩니다.
# 환경변수 GOOGLE_API_KEYS 에 쉼표(,)로 구분해서 여러 개 등록하세요.
# 예) GOOGLE_API_KEYS="key1,key2,key3"
GOOGLE_API_KEYS = [
    key.strip() for key in os.getenv("GOOGLE_API_KEYS", "").split(",") if key.strip()
]

GEMINI_MODEL_NAME = "gemini-2.5-flash"

DEVELOPER_ID = 1138279240589127750
DEVELOPER_IDS = [DEVELOPER_ID] 

ALLOWED_ADMIN_IDS = [1138279240589127750]
DEVELOPERS = ["1138279240589127750"]

GUILD_ID = 1381422203161284618


# 서버 관리자 권한 (discord.Permissions)
# 이 권한이 있는 유저가 서버 설정 커맨드를 사용할 수 있음
SERVER_ADMIN_PERMISSION = "manage_guild"
0

# ── 디스호스트 API ──
DISHOST_API_KEY = os.getenv("DISHOST_API_KEY", "")
DISHOST_API_URL = os.getenv("DISHOST_API_URL", "https://listapi.dishost.kr")
DISHOST_STATS_INTERVAL = 3600  # 1시간(초)

# ── 투표 보상 ──
VOTE_REWARD_BASE = 1000        # 기본 보상 골드
VOTE_STREAK_BONUS = 500       # 연속 투표 1일당 추가 골드
VOTE_STREAK_MAX_BONUS = 10000  # 연속 보너스 상한
VOTE_MILESTONE_REWARDS = {     # 누적 투표 마일스톤 보상
    7:   {"gold": 2000,  "label": "🥉 7일 투표"},
    14:  {"gold": 5000,  "label": "🥈 14일 투표"},
    30:  {"gold": 12000, "label": "🥇 30일 투표"},
    60:  {"gold": 30000, "label": "💎 60일 투표"},
    100: {"gold": 50000, "label": "👑 100일 투표"},
}


# ═══════════════════════════════════════════════════════════
# 웹훅 URL
# ═══════════════════════════════════════════════════════════

ADMIN_WEBHOOK_URL = os.getenv("ADMIN_WEBHOOK_URL", "")
REPORT_WEBHOOK_URL = os.getenv("REPORT_WEBHOOK_URL", "")
WELCOME_WEBHOOK_URL = os.getenv("WELCOME_WEBHOOK_URL", "")
RARE_CATCH_WEBHOOK_URL = os.getenv("RARE_CATCH_WEBHOOK_URL", "")
ANTICHEAT_WEBHOOK_URL = os.getenv("ANTICHEAT_WEBHOOK_URL", ADMIN_WEBHOOK_URL)

# ═══════════════════════════════════════════════════════════
# 디렉토리 / 파일 경로
# ═══════════════════════════════════════════════════════════

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
USERS_DIR = os.path.join(BASE_DIR, "users")
IMAGES_DIR = os.path.join(BASE_DIR, "images")
BACKUP_DIR = os.path.join(BASE_DIR, "backup")
GUILDS_DIR = os.path.join(BASE_DIR, "data", "guilds")

CATS_FILE = os.path.join(DATA_DIR, "cats.json")
REGIONS_FILE = os.path.join(DATA_DIR, "regions.json")
EQUIPMENT_FILE = os.path.join(DATA_DIR, "equipment.json")
BOSSES_FILE = os.path.join(DATA_DIR, "bosses.json")
LABYRINTH_FILE = os.path.join(DATA_DIR, "labyrinth.json")

BLOCKLIST_FILE = os.path.join(BASE_DIR, "blocked_servers.json")
BAN_FILE = os.path.join(BASE_DIR, "user_ban.json")
COUPON_FILE = os.path.join(BASE_DIR, "coupons.json")
USED_COUPON_FILE = os.path.join(BASE_DIR, "used_coupons.json")
NOTI_CHANNELS_FILE = os.path.join(BASE_DIR, "noti_channels.json")
STATS_FILE = os.path.join(BASE_DIR, "monthly_stats.json")
DEATH_LOG_PATH = os.path.join(DATA_DIR, "death_log.json")

KAYOKO_SETTINGS_FILE = os.path.join(BASE_DIR, "kayoko_settings.json")
KAYOKO_USAGE_FILE = os.path.join(BASE_DIR, "user_usage.json")

VERIFICATION_CONFIG_FILE = os.path.join(BASE_DIR, "verification_config.json")
VERIFICATION_ATTEMPTS_FILE = os.path.join(BASE_DIR, "user_attempts.json")

# ═══════════════════════════════════════════════════════════
# 시간대
# ═══════════════════════════════════════════════════════════

KST = ZoneInfo("Asia/Seoul")

# ═══════════════════════════════════════════════════════════
# 임베드 색상
# ═══════════════════════════════════════════════════════════

COLOR_DEFAULT = 0xF8A8C4
COLOR_SUCCESS = 0x57F287
COLOR_ERROR = 0xED4245
COLOR_WARNING = 0xFEE75C
COLOR_INFO = 0x5865F2
COLOR_PRIMARY = COLOR_INFO

COLOR_COMMON = 0x95A5A6
COLOR_UNCOMMON = 0x2ECC71
COLOR_RARE = 0x3498DB
COLOR_EPIC = 0x9B59B6
COLOR_LEGENDARY = 0xF1C40F
COLOR_MYTHIC = 0xE74C3C

# ═══════════════════════════════════════════════════════════
# 성장 시스템 (밸런스 v2 — 레벨 70 기준)
# ═══════════════════════════════════════════════════════════

MAX_LEVEL = 70
BASE_EXP_REQUIRED = 100
EXP_INCREMENT_PER_LEVEL = 60
EXP_LATEGAME_BONUS_PER_LEVEL = 40
EXP_LATEGAME_THRESHOLD = 30


def get_exp_for_level(level: int) -> int:
    if level >= MAX_LEVEL:
        return 999999999
    base = BASE_EXP_REQUIRED + (level - 1) * EXP_INCREMENT_PER_LEVEL
    if level >= EXP_LATEGAME_THRESHOLD:
        base += (level - EXP_LATEGAME_THRESHOLD) * EXP_LATEGAME_BONUS_PER_LEVEL
    return base


# 스킬 트리
SKILL_TREE_TRACKING = "tracking"
SKILL_TREE_COMBAT = "combat"
SKILL_TREE_TRADE = "trade"

SKILL_POINTS_PER_LEVEL = 1
MAX_SKILL_LEVEL = 25

SKILL_EFFECTS = {
    SKILL_TREE_TRACKING: {
        "kidnap_success_bonus": 0.4,
        "rare_chance_bonus": 0.25,
        "hint_accuracy_bonus": 1.8,
    },
    SKILL_TREE_COMBAT: {
        "battle_power_bonus": 2.5,
        "battle_hp_bonus": 8,
        "skill_damage_bonus": 1.5,
    },
    SKILL_TREE_TRADE: {
        "sell_price_bonus": 2.5,
        "shop_discount": 0.8,
        "daily_bonus_money": 400,
    },
}

# ═══════════════════════════════════════════════════════════
# 일일 제한 시스템
# ═══════════════════════════════════════════════════════════

DAILY_LIMITS = {
    "kidnap": 100,
    "battle": 30,
    "labyrinth": 5,
    "gamble": 20,
    "equipment_buy": 10,
    "gamble": 25,
}

# ═══════════════════════════════════════════════════════════
# 매크로/자동화 탐지 시스템
# ═══════════════════════════════════════════════════════════

ANTICHEAT_ENABLED = True
ANTICHEAT_REACTION_WINDOW_MS = 50
ANTICHEAT_REACTION_CONSECUTIVE = 5
ANTICHEAT_COMMANDS_PER_MINUTE = 15
ANTICHEAT_KIDNAPS_PER_HOUR = 60
ANTICHEAT_MAX_WARNINGS = 5
ANTICHEAT_WARNING_DECAY_DAYS = 9999999

# ═══════════════════════════════════════════════════════════
# 뉴비 보호 시스템
# ═══════════════════════════════════════════════════════════

NEWBIE_PROTECTION_DAYS = 7
NEWBIE_DEATH_PENALTY_EXEMPT = True
CATCHUP_EXP_BONUS_MAX = 1.0
CATCHUP_LEVEL_REFERENCE = 20

# ═══════════════════════════════════════════════════════════
# 납치 시스템 (밸런스 v2)
# ═══════════════════════════════════════════════════════════

KIDNAP_BASE_COOLDOWN = 18
KIDNAP_MIN_COOLDOWN = 8
KIDNAP_BASE_SUCCESS_RATE = 60.0
KIDNAP_MAX_SUCCESS_RATE = 92.0
KIDNAP_MIN_SUCCESS_RATE = 20.0

REACTION_PERFECT_MS = 500
REACTION_GREAT_MS = 1500
REACTION_GOOD_MS = 3000
REACTION_TIMEOUT_MS = 10000

REACTION_PERFECT_BONUS = 12.0
REACTION_GREAT_BONUS = 6.0
REACTION_GOOD_BONUS = 2.0
REACTION_TIMEOUT_PENALTY = -15.0

KIDNAP_LOCATION_COUNT = 3

KIDNAP_SEARCHING_MESSAGES = [
    "풀숲 사이로 무언가 움직입니다...",
    "발자국 소리가 들리는 것 같습니다...",
    "조용히 주변을 살피는 중...",
    "냥이의 흔적을 추적합니다...",
    "어디선가 야옹 소리가...",
    "바람이 불어옵니다... 집중하세요.",
    "그림자가 스쳐지나갔습니다...",
    "인내심을 가지고 기다리는 중...",
    "조심스럽게 접근합니다...",
    "근처에 무언가 있는 것 같습니다...",
]

KIDNAP_ACTIVATE_MESSAGES = [
    "❗ 지금이다! 잡아!!",
    "❗ 발견했다! 놓치지 마!!",
    "❗ 저기 있다! 빨리!!",
    "❗ 냥이를 포착했다! 잡아라!!",
    "❗ 움직임을 감지! 지금이야!!",
]

KIDNAP_FAKE_MESSAGES = [
    "❓ 어...? 뭔가 보인 것 같은데...",
    "❓ 잠깐, 저건 냥이가 아니라...",
    "❓ 바스락... 바람인가?",
]

KIDNAP_FAKE_BUTTON_LABELS = [
    "잡아!!",
    "지금이다!",
    "포획!",
]

KIDNAP_REAL_BUTTON_LABELS = [
    "🐾 잡아!!",
    "🐾 포획!",
    "🐾 지금이다!",
]

# ═══════════════════════════════════════════════════════════
# 희귀도 등급 정의
# ═══════════════════════════════════════════════════════════

RARITY_TIERS = {
    "common": {
        "name": "일반", "emoji": "⬜", "color": COLOR_COMMON,
        "min_rarity": 15.0, "catch_exp": 5,
        "sell_price_range": (300, 1000), "announcement": False,
    },
    "uncommon": {
        "name": "고급", "emoji": "🟩", "color": COLOR_UNCOMMON,
        "min_rarity": 5.0, "catch_exp": 12,
        "sell_price_range": (1500, 4000), "announcement": False,
    },
    "rare": {
        "name": "희귀", "emoji": "🟦", "color": COLOR_RARE,
        "min_rarity": 1.0, "catch_exp": 30,
        "sell_price_range": (6000, 15000), "announcement": False,
    },
    "epic": {
        "name": "영웅", "emoji": "🟪", "color": COLOR_EPIC,
        "min_rarity": 0.1, "catch_exp": 80,
        "sell_price_range": (20000, 50000), "announcement": True,
    },
    "legendary": {
        "name": "전설", "emoji": "🟨", "color": COLOR_LEGENDARY,
        "min_rarity": 0.01, "catch_exp": 250,
        "sell_price_range": (80000, 200000), "announcement": True,
    },
    "mythic": {
        "name": "신화", "emoji": "🟥", "color": COLOR_MYTHIC,
        "min_rarity": 0.0, "catch_exp": 800,
        "sell_price_range": (400000, 1000000), "announcement": True,
    },
}


def get_rarity_tier(rarity_percent: float) -> dict:
    for tier_key in ["common", "uncommon", "rare", "epic", "legendary", "mythic"]:
        tier = RARITY_TIERS[tier_key]
        if rarity_percent >= tier["min_rarity"]:
            return {**tier, "key": tier_key}
    return {**RARITY_TIERS["mythic"], "key": "mythic"}


# ═══════════════════════════════════════════════════════════
# 경제 상수 (밸런스 v2)
# ═══════════════════════════════════════════════════════════

KIDNAP_BASE_MONEY_REWARD = 80
DAILY_LOGIN_REWARD = 800
TUTORIAL_COMPLETION_REWARD = 8000

GAMBLE_MIN_BET = 1000
GAMBLE_MAX_BET = 30000

MONEY_SOFT_CAP_BASE = 500000
MONEY_SOFT_CAP_PER_LEVEL = 20000

# ═══════════════════════════════════════════════════════════
# 전투 시스템 (밸런스 v2)
# ═══════════════════════════════════════════════════════════

BATTLE_MIN_LEVEL = 3
BATTLE_DIFFICULTY_LEVEL_REQ = {1: 3, 2: 8, 3: 15}
BATTLE_COOLDOWN_SECONDS = 30

# ═══════════════════════════════════════════════════════════
# 미궁 시스템 (밸런스 v2)
# ═══════════════════════════════════════════════════════════

LABYRINTH_MIN_LEVEL = 10
LABYRINTH_MIN_CATS = 3
LABYRINTH_COOLDOWN_SECONDS = 180

# ═══════════════════════════════════════════════════════════
# 주간 보스 시스템
# ═══════════════════════════════════════════════════════════

WEEKLY_BOSS_ENABLED = True
WEEKLY_BOSS_MIN_LEVEL = 40
WEEKLY_BOSS_RESET_DAY = 0
WEEKLY_BOSS_MAX_ATTEMPTS = 3

WEEKLY_BOSS_TEMPLATES = {
    "shadow_lord": {
        "name": "그림자 군주", "hp": 5000, "attack": 80,
        "description": "심연에서 올라온 거대한 그림자의 군주.",
        "rewards": {
            "money": (15000, 30000), "exp": (500, 1000),
            "tuna_can": (3, 5), "title": "그림자 정복자",
        },
    },
    "crystal_guardian": {
        "name": "결정의 수호자", "hp": 7000, "attack": 65,
        "description": "고대 미궁의 핵심을 지키는 수정 괴물.",
        "rewards": {
            "money": (20000, 40000), "exp": (600, 1200),
            "tuna_can": (4, 7), "title": "결정 파괴자",
        },
    },
    "chaos_emperor": {
        "name": "혼돈의 황제", "hp": 10000, "attack": 100,
        "description": "모든 것을 집어삼키는 혼돈의 화신.",
        "rewards": {
            "money": (30000, 60000), "exp": (800, 1500),
            "tuna_can": (5, 10), "title": "혼돈의 정복자",
        },
    },
}

# ═══════════════════════════════════════════════════════════
# 도전 과제 시스템
# ═══════════════════════════════════════════════════════════

ACHIEVEMENTS = {
    "first_catch": {"name": "첫 포획", "desc": "냥이를 처음으로 납치합니다.", "reward_money": 500, "reward_exp": 20},
    "collector_10": {"name": "수집가 I", "desc": "냥이 10종 수집", "reward_money": 3000, "reward_exp": 100},
    "collector_25": {"name": "수집가 II", "desc": "냥이 25종 수집", "reward_money": 10000, "reward_exp": 300},
    "collector_all": {"name": "완벽한 수집가", "desc": "모든 냥이 수집", "reward_money": 100000, "reward_exp": 5000},
    "battle_10": {"name": "전사 I", "desc": "전투 10회 승리", "reward_money": 2000, "reward_exp": 80},
    "battle_100": {"name": "전사 II", "desc": "전투 100회 승리", "reward_money": 15000, "reward_exp": 500},
    "labyrinth_10": {"name": "탐험가 I", "desc": "미궁 10층 도달", "reward_money": 5000, "reward_exp": 200},
    "labyrinth_30": {"name": "탐험가 II", "desc": "미궁 30층 도달", "reward_money": 20000, "reward_exp": 800},
    "labyrinth_50": {"name": "미궁 마스터", "desc": "미궁 50층 도달", "reward_money": 50000, "reward_exp": 2000},
    "level_10": {"name": "성장 I", "desc": "레벨 10 도달", "reward_money": 1000, "reward_exp": 50},
    "level_25": {"name": "성장 II", "desc": "레벨 25 도달", "reward_money": 5000, "reward_exp": 200},
    "level_50": {"name": "성장 III", "desc": "레벨 50 도달", "reward_money": 20000, "reward_exp": 1000},
    "level_70": {"name": "만렙 달성", "desc": "레벨 70 도달", "reward_money": 100000, "reward_exp": 0},
    "weekly_boss_first": {"name": "주간 보스 첫 처치", "desc": "주간 보스를 처음으로 처치", "reward_money": 10000, "reward_exp": 500},
    "rich_100k": {"name": "부자 I", "desc": "소지금 100,000원 달성", "reward_money": 0, "reward_exp": 100},
    "rich_1m": {"name": "부자 II", "desc": "소지금 1,000,000원 달성", "reward_money": 0, "reward_exp": 500},
}

# ═══════════════════════════════════════════════════════════
# 자동 납치 상수
# ═══════════════════════════════════════════════════════════

AUTO_KIDNAP_BASE_DURATION = 180
AUTO_KIDNAP_UPGRADE_PER_LEVEL = 60
AUTO_KIDNAP_MAX_LEVEL = 7

# ═══════════════════════════════════════════════════════════
# 튜토리얼 단계 정의
# ═══════════════════════════════════════════════════════════

TUTORIAL_STEPS = {
    "welcome": {
        "step": 0, "title": "카요코와의 만남",
        "description": "카요코 봇에 오신 것을 환영합니다! 기본적인 사용법을 알려드릴게요.",
        "reward_money": 800, "reward_exp": 0, "next": "first_kidnap",
    },
    "first_kidnap": {
        "step": 1, "title": "첫 번째 납치",
        "description": "`/납치` 명령어를 사용하여 첫 냥이를 납치해보세요!",
        "reward_money": 1500, "reward_exp": 40, "next": "check_inventory",
    },
    "check_inventory": {
        "step": 2, "title": "인벤토리 확인",
        "description": "`/냥이인벤토리` 명령어로 획득한 냥이를 확인해보세요!",
        "reward_money": 800, "reward_exp": 25, "next": "visit_shop",
    },
    "visit_shop": {
        "step": 3, "title": "상점 방문",
        "description": "`/상점` 명령어로 상점을 둘러보세요!",
        "reward_money": 2000, "reward_exp": 40, "next": "level_up",
    },
    "level_up": {
        "step": 4, "title": "성장의 시작",
        "description": "레벨 3에 도달해보세요! 납치를 반복하면 경험치를 얻을 수 있습니다.",
        "reward_money": 4000, "reward_exp": 80, "next": "complete",
    },
    "complete": {
        "step": 5, "title": "튜토리얼 완료!",
        "description": "축하합니다! 이제 자유롭게 모험을 즐기세요!",
        "reward_money": TUTORIAL_COMPLETION_REWARD, "reward_exp": 150, "next": None,
    },
}

# ═══════════════════════════════════════════════════════════
# 봇 UI 상수
# ═══════════════════════════════════════════════════════════

BOT_ICON_URL = "https://media.discordapp.net/attachments/1267472211531530311/1483080232620523613/KakaoTalk_20251210_215802552.png?ex=69c72159&is=69c5cfd9&hm=a1c4d1bb4d47df3f3519037853cd9d57c1e0c00b90784282543d7358011e31cb&=&format=webp&quality=lossless&width=930&height=930"

LOCATION_EMOJIS = [
    ("🗑️", "쓰레기통 뒤"),
    ("🌳", "나무 위"),
    ("📦", "박스 안"),
    ("🚗", "차 밑"),
    ("🏚️", "빈집 안"),
    ("🌿", "풀숲 속"),
    ("🪨", "바위 뒤"),
    ("🏗️", "공사장"),
    ("🛝", "놀이터"),
    ("🏪", "편의점 옆"),
    ("⛲", "분수대 근처"),
    ("🚂", "기차역 구석"),
]

# ═══════════════════════════════════════════════════════════
# 임베드 UI 상수
# ═══════════════════════════════════════════════════════════

BAR_FILLED = "█"
BAR_EMPTY = "░"
BAR_DEFAULT_LENGTH = 15

HP_BAR_HIGH = "🟩"
HP_BAR_MID = "🟨"
HP_BAR_LOW = "🟥"
HP_BAR_EMPTY = "⬛"

SP_BAR_FILLED = "🔵"
SP_BAR_EMPTY = "⚫"

EMBED_SEPARATOR = "━━━━━━━━━━━━━━━━━━━━"
EMBED_THIN_SEPARATOR = "─────────────────"

# ═══════════════════════════════════════════════════════════
# 디렉토리 자동 생성
# ═══════════════════════════════════════════════════════════

for _dir in [DATA_DIR, USERS_DIR, IMAGES_DIR, BACKUP_DIR, GUILDS_DIR]:
    os.makedirs(_dir, exist_ok=True)

# ═══════════════════════════════════════════════════════════
# 호환용 별칭
# ═══════════════════════════════════════════════════════════

SEPARATOR = EMBED_THIN_SEPARATOR
RARITY_COLORS = {k: v["color"] for k, v in RARITY_TIERS.items()}
RARITY_ORDER = ["common", "uncommon", "rare", "epic", "legendary", "mythic"]
KIDNAP_HARD_CAP = 0.85
EMBED_FOOTER_TEXT = "카요코 봇"
BAR_FULL = BAR_FILLED
BAR_EMPTY_CHAR = BAR_EMPTY
ICON_URL = BOT_ICON_URL
BOT_ICON = BOT_ICON_URL
WEEKLY_BOSS_CONFIG = WEEKLY_BOSS_TEMPLATES
EXP_FOR_LEVEL = get_exp_for_level
SKILL_BONUSES = SKILL_EFFECTS
RARITY_EMOJI = {k: v["emoji"] for k, v in RARITY_TIERS.items()}
RARITY_NAMES = {k: v["name"] for k, v in RARITY_TIERS.items()}
ADMIN_IDS = ALLOWED_ADMIN_IDS

# ── gameplay.py 호환 ──
TUTORIAL_COMPLETE_REWARD = TUTORIAL_COMPLETION_REWARD
KIDNAP_BASE_REWARD = KIDNAP_BASE_MONEY_REWARD
