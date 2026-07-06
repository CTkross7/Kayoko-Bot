# data_manager.py
# ──────────────────────────────────────────────────────────
# JSON 파일 I/O 유틸리티 (서버별 설정 지원)
# ──────────────────────────────────────────────────────────

import os
import json

from config import USERS_DIR, GUILDS_DIR


# ═══════════════════════════════════════════════════════════
# 기본 JSON I/O
# ═══════════════════════════════════════════════════════════

def load_json(filepath: str, default=None):
    if default is None:
        default = {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return default


def save_json(filepath: str, data):
    dir_path = os.path.dirname(filepath)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════
# 유저 데이터 경로 (전역 — 방식 A)
# ═══════════════════════════════════════════════════════════

def get_user_filepath(user_id: str) -> str:
    return os.path.join(USERS_DIR, f"{user_id}.json")


# ═══════════════════════════════════════════════════════════
# 서버별 설정 I/O
# ═══════════════════════════════════════════════════════════

def _guild_dir(guild_id) -> str:
    return os.path.join(GUILDS_DIR, str(guild_id))


def _guild_config_path(guild_id) -> str:
    return os.path.join(_guild_dir(guild_id), "guild_config.json")


def _default_guild_config(guild_id, guild_name: str = "") -> dict:
    return {
        "guild_id": str(guild_id),
        "guild_name": guild_name,
        "notice_channel_id": None,
        "notice_channel_name": None,
        "welcome_channel_id": None,
        "bot_enabled": True,
        "created_at": None,
    }


def load_guild_config(guild_id) -> dict:
    path = _guild_config_path(guild_id)
    data = load_json(path, None)
    if data is None:
        return _default_guild_config(guild_id)
    # 기본값 보충
    defaults = _default_guild_config(guild_id)
    updated = False
    for key, val in defaults.items():
        if key not in data:
            data[key] = val
            updated = True
    if updated:
        save_guild_config(guild_id, data)
    return data


def save_guild_config(guild_id, data: dict):
    path = _guild_config_path(guild_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_json(path, data)


def get_all_guild_configs() -> dict:
    """모든 서버 설정을 로드합니다. {guild_id_str: config_dict}"""
    result = {}
    if not os.path.isdir(GUILDS_DIR):
        return result
    for name in os.listdir(GUILDS_DIR):
        config_path = os.path.join(GUILDS_DIR, name, "guild_config.json")
        if os.path.isfile(config_path):
            data = load_json(config_path, {})
            result[name] = data
    return result


def get_guilds_with_notice_channel() -> list:
    """공지 채널이 설정된 서버 목록을 반환합니다. [(guild_id, config), ...]"""
    result = []
    all_configs = get_all_guild_configs()
    for gid, config in all_configs.items():
        if config.get("notice_channel_id"):
            result.append((gid, config))
    return result
