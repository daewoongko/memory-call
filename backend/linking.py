"""
기기 연동.

보호자가 코드를 만들고 어르신 기기에 입력한다.
계정과 비밀번호 대신 여섯 자리 숫자를 쓰는 이유는,
치매가 있는 분이 아이디와 비밀번호를 입력할 수 없기 때문이다.

코드는 한 번 쓰면 만료된다.
"""

import random
from datetime import datetime, timedelta

import db

VALID_MINUTES = 30


def issue(elder_id: str = "elder_001") -> dict:
    code = f"{random.randint(0, 999999):06d}"
    expires = datetime.now() + timedelta(minutes=VALID_MINUTES)

    with db.connect() as conn:
        # 지난 코드는 지운다. 여러 개가 살아 있으면 어느 것이 유효한지 헷갈린다.
        conn.execute("DELETE FROM link_codes WHERE elder_id = ?", (elder_id,))
        db.insert(conn, "link_codes", {
            "code": code,
            "elder_id": elder_id,
            "expires_at": expires.isoformat(timespec="seconds"),
        })
        conn.commit()

    return {
        "code": code,
        "expires_at": expires.isoformat(timespec="seconds"),
        "valid_minutes": VALID_MINUTES,
    }


def verify(code: str) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM link_codes WHERE code = ? AND used_at IS NULL",
            (code.strip(),),
        ).fetchone()
        if row is None:
            raise ValueError("코드가 맞지 않아요. 다시 확인해 주세요.")
        if row["expires_at"] < now:
            raise ValueError("코드가 만료되었어요. 보호자에게 새 코드를 받아주세요.")

        conn.execute("UPDATE link_codes SET used_at = ? WHERE code = ?", (now, code))
        elder = conn.execute(
            "SELECT elder_id, name FROM elder_profiles WHERE elder_id = ?",
            (row["elder_id"],),
        ).fetchone()
        conn.commit()

    return {"elder_id": row["elder_id"], "name": elder["name"] if elder else ""}
