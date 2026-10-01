"""错误码 → 小白话（PRD §六）。"""
import psycopg2

MESSAGES = {
    "table_missing": "没找到「{d}」这张表，表可能刚被重新导入过。请刷新页面重试",
    "col_missing": "没找到「{d}」这一列，表可能刚重新导入过。请刷新页面重试",
    "no_pairs": "还没有勾选两边对应的字段，先完成「对应字段」这一步",
    "bad_kind": "操作类型不对，请回到首页重新选择",
    "conn_failed": "数据库没启动，请先启动 PostgreSQL 再刷新页面",
    "lock_timeout": "表正被其他操作占用，稍等 10 秒再试",
    "type_cast": "两边字段内容类型对不上（一边是数字一边是文字），换一个对应列试试",
    "zero_match": "按现在的对应关系一个都没对上，检查两边勾选的字段是不是配错了",
    "backup_failed": "备份没建成，已中止 —— 你的数据没动。稍后重试",
    "update_zero": "表结构刚变过，一条都没更新到，已中止。刷新页面后重新执行",
}


def humanize(exc) -> str:
    code = getattr(exc, "code", None)
    if code and code in MESSAGES:
        return MESSAGES[code].format(d=getattr(exc, "detail", ""))
    if type(exc).__name__ == "ConfigMissing":
        return "找不到数据库配置文件（excel2pg 的 .env），请确认它还在原位置"
    name, msg = type(exc).__name__, str(exc)
    # 锁/超时必须先于 OperationalError 判断（QueryCanceledError 是它的子类）
    if any(k in msg.lower() for k in ("lock timeout", "deadlock", "lock wait")) or "Lock" in name:
        return MESSAGES["lock_timeout"]
    if isinstance(exc, (psycopg2.OperationalError, ConnectionError)):
        return MESSAGES["conn_failed"]
    if "UndefinedFunction" in name or "invalid input syntax" in msg:
        return MESSAGES["type_cast"]
    if "does not exist" in msg and '"' in msg:
        return MESSAGES["col_missing"].format(d=msg.split('"')[1])
    return f"出了点问题：{msg}"
