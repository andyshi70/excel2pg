"""DB 连接与标识符安全。凭据来自 excel2pg/.env，永不回传/打印。"""
import os
from contextlib import contextmanager

import psycopg2
from dotenv import load_dotenv

ENV_PATH = "/Users/evandy/excel2pg/.env"


def get_conn():
    load_dotenv(ENV_PATH)
    return psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )


@contextmanager
def connect():
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


def qi(ident: str) -> str:
    """引用标识符（中文表名/列名安全）。"""
    return '"' + ident.replace('"', '""') + '"'


def qstr(val) -> str:
    """SQL 字符串字面量，转义单引号。"""
    return "'" + str(val).replace("'", "''") + "'"


def columns(conn, table: str) -> list:
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s",
        (table,),
    )
    return {r[0]: r[1] for r in cur.fetchall()}


def table_exists(conn, table: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name=%s",
        (table,),
    )
    return cur.fetchone() is not None


def list_tables(conn) -> list:
    cur = conn.cursor()
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' ORDER BY table_name"
    )
    return [r[0] for r in cur.fetchall()]
