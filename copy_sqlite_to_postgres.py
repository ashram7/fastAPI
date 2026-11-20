"""
SQLite → PostgreSQL 데이터 복사 (일회용, 한 번에 실행)

사용법 (프로젝트 폴더에서)
  1) 아래 PG_URL 에 Render의 External Database URL을 붙여 넣고 저장
  2) python copy_sqlite_to_postgres.py

하는 일
  1) models.py의 테이블 정의로 PostgreSQL에 테이블 생성 (이미 있으면 건너뜀)
  2) alembic_version(마이그레이션 버전)도 함께 생성·복사
  3) SQLite 데이터를 외래키 순서대로 복사 (PostgreSQL 기존 데이터는 비우고 복사)
  4) id 번호 이어 붙이기 (복사 후 새 글 작성 시 duplicate key 방지)

alembic.ini, .env 등 기존 설정 파일은 전혀 건드리지 않습니다.
"""
import os
import sys

from sqlalchemy import (Boolean, Column, MetaData, String, Table, create_engine,
                        inspect, select, text)

# ▼▼▼ 여기만 수정 ▼▼▼
SQLITE_FILE = "myapi.db"
PG_URL = ""   # 예: "postgresql://user:비밀번호@호스트.singapore-postgres.render.com/DB이름"
# ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲

BATCH_SIZE = 1000


def normalize_pg_url(url):
    # 드라이버를 psycopg2로 명시 (SQLAlchemy 버전에 따라 기본 드라이버가 다름)
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg2://" + url[len(prefix):]
    # Render 외부 접속은 SSL 필요
    if "sslmode=" not in url and "localhost" not in url and "127.0.0.1" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def main():
    pg_url = PG_URL or os.environ.get("DATABASE_URL")
    if not pg_url:
        sys.exit("PG_URL이 비어 있습니다. 스크립트 위쪽 PG_URL에 Render 주소를 넣어 주세요.")
    if not os.path.exists(SQLITE_FILE):
        sys.exit(f"SQLite 파일을 찾을 수 없습니다: {SQLITE_FILE} (프로젝트 폴더에서 실행하세요)")

    try:
        from models import Base  # 프로젝트의 테이블 정의
    except ImportError as e:
        sys.exit(f"models.py를 불러오지 못했습니다: {e}\n프로젝트 폴더에서 실행하세요.")

    src_engine = create_engine(f"sqlite:///{SQLITE_FILE}")
    dst_engine = create_engine(normalize_pg_url(pg_url))

    # 테이블 목록: 모델 테이블 + (있으면) alembic_version
    metadata = MetaData()
    for t in Base.metadata.sorted_tables:
        t.to_metadata(metadata)
    src_tables = set(inspect(src_engine).get_table_names())
    if "alembic_version" in src_tables:
        Table("alembic_version", metadata,
              Column("version_num", String(32), primary_key=True))
    tables = [t for t in metadata.sorted_tables if t.name in src_tables]

    # 1) PostgreSQL에 테이블 생성 (이미 있는 테이블은 그대로 둠)
    metadata.create_all(dst_engine)
    print("PostgreSQL 테이블 준비 완료")

    with src_engine.connect() as src, dst_engine.begin() as dst:
        # 대상에 이미 데이터가 있으면 확인 후 진행
        existing = {t.name: dst.execute(text(
            f"SELECT COUNT(*) FROM {dst.dialect.identifier_preparer.quote(t.name)}")).scalar()
            for t in tables}
        existing = {k: v for k, v in existing.items() if v}
        if existing:
            print(f"PostgreSQL에 이미 데이터가 있습니다: {existing}")
            if input("모두 지우고 SQLite 데이터로 덮어쓸까요? (y/N): ").strip().lower() != "y":
                sys.exit("취소했습니다. 아무것도 바뀌지 않았습니다.")
            for t in reversed(tables):  # 자식 테이블부터 삭제
                dst.execute(t.delete())

        # 2) 데이터 복사
        for table in tables:
            src_cols = {c["name"] for c in inspect(src_engine).get_columns(table.name)}
            cols = [c for c in table.columns if c.name in src_cols]
            bool_cols = [c.name for c in cols if isinstance(c.type, Boolean)]

            result = src.execute(select(*cols))  # 모델 타입으로 읽음 (날짜 등 자동 변환)
            count = 0
            while True:
                rows = result.mappings().fetchmany(BATCH_SIZE)
                if not rows:
                    break
                batch = []
                for r in rows:
                    row = dict(r)
                    for name in bool_cols:  # SQLite의 0/1 → True/False
                        if row[name] is not None:
                            row[name] = bool(row[name])
                    batch.append(row)
                dst.execute(table.insert(), batch)
                count += len(batch)
            print(f"  {table.name}: {count}건 복사")

        # 3) id 번호 이어 붙이기
        for table in tables:
            if "id" in table.c:
                q = dst.dialect.identifier_preparer.quote(table.name)
                seq = dst.execute(text("SELECT pg_get_serial_sequence(:t, 'id')"),
                                  {"t": q}).scalar()
                if seq:
                    dst.execute(text(
                        f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {q}), 0) + 1, false)"))

    print("완료: SQLite → PostgreSQL 복사가 끝났습니다.")


if __name__ == "__main__":
    main()
