# copy_db.py  -  사용법: python copy_db.py "원본 DB 주소" "대상 DB 주소"
#
# 원본(예: SQLite) 데이터는 id 그대로 넣고,
# 대상(예: PostgreSQL)에 원래 있던 데이터는 그 뒤 번호로 이어 붙입니다.
#   - 같은 username/email의 사용자는 하나로 합침 (원본 쪽 정보 유지)
#   - 내용이 완전히 같은 글·답변·추천은 한 번만 남김
#   - 번호가 바뀐 사용자·질문을 가리키는 user_id, question_id 등도 함께 고쳐서 연결 유지
# 전체가 하나의 트랜잭션이라, 중간에 오류가 나면 대상 DB는 원래대로 돌아갑니다.
import sys
from sqlalchemy import create_engine, text
from models import Base            # 테이블 정의

src = create_engine(sys.argv[1])
dst = create_engine(sys.argv[2])
Base.metadata.create_all(dst)      # 대상 DB에 테이블이 없으면 생성 (이미 있으면 그대로 둠)
tables = Base.metadata.sorted_tables   # user > question > answer 순서


def unique_cols(table):
    """중복 사용자 판별용: unique=True 컬럼 (예: user.username, user.email)"""
    return [c.name for c in table.columns if c.unique]


with src.connect() as s, dst.begin() as d:
    # 1) 대상 DB의 기존 데이터를 메모리에 보관한 뒤 비움
    old = {t.name: [dict(r._mapping) for r in d.execute(t.select())] for t in tables}
    for t in reversed(tables):     # 자식 테이블부터 삭제
        d.execute(t.delete())

    id_map = {}                    # {테이블명: {예전 id: 새 id}}
    for table in tables:
        # 2) 원본 데이터를 id 그대로 넣음
        rows = [dict(r._mapping) for r in s.execute(table.select())]
        if rows:
            d.execute(table.insert(), rows)

        has_id = "id" in table.c
        uniq = unique_cols(table)
        # 중복 비교용: id를 뺀 나머지 값 전체
        def key(row):
            return tuple(row[c.name] for c in table.columns if c.name != "id")
        by_key = {key(r): r.get("id") for r in rows}
        by_uniq = {(c, r[c]): r["id"] for r in rows for c in uniq if r[c] is not None}
        next_id = max([r["id"] for r in rows if r["id"] is not None], default=0) + 1 if has_id else None

        # 3) 대상 DB에 있던 데이터를 뒤에 이어 붙임
        mapping, added, skipped = {}, [], 0
        for row in old[table.name]:
            # 다른 테이블을 가리키는 번호(user_id, question_id 등)를 바뀐 번호로 고침
            for col in table.columns:
                for fk in col.foreign_keys:
                    ref = fk.column.table.name
                    if row[col.name] is not None and row[col.name] in id_map.get(ref, {}):
                        row[col.name] = id_map[ref][row[col.name]]

            # 같은 username/email의 사용자 → 기존 사용자로 합침
            match = next((by_uniq[(c, row[c])] for c in uniq if (c, row[c]) in by_uniq), None)
            # 내용이 완전히 같은 행 → 건너뜀
            if match is None and key(row) in by_key:
                match = by_key[key(row)] if has_id else True
            if match is not None:
                if has_id:
                    mapping[row["id"]] = match
                skipped += 1
                continue

            if has_id:
                mapping[row["id"]] = next_id
                row["id"] = next_id
                next_id += 1
            by_key[key(row)] = row.get("id")
            added.append(row)

        if added:
            d.execute(table.insert(), added)
        id_map[table.name] = mapping
        print(f"{table.name}: 원본 {len(rows)}건 + 기존 데이터 {len(added)}건 추가 (중복 {skipped}건 제외)")

    if dst.dialect.name == "postgresql":           # 번호 이어 붙이기
        for table in tables:
            if "id" in table.c:
                d.execute(text(f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', 'id'), "
                               f"COALESCE((SELECT MAX(id) FROM \"{table.name}\"), 0) + 1, false)"))
