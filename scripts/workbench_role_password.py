#!/usr/bin/env python3
"""给工作台的只读角色 tv_workbench_ro 设密码 (W-63, docs/35 第 4 节)。只用标准库; 不连库、不联网、不写文件。

为什么要它: 生产库 log_statement = ddl, 在 SQL editor 里写 ALTER ROLE ... PASSWORD '明文' 会原样进 Postgres 日志。
这里在本机生成密码, 按 Postgres 的 SCRAM-SHA-256 算出校验串; SQL editor 里只贴带校验串的那一句, 日志里就没有明文。
Postgres 认出值是 SCRAM-SHA-256$... 的校验串, 原样存下, 不再算一遍。

  python3 scripts/workbench_role_password.py             生成一个 40 位字母数字的密码, 打出两样:
                                                         ① 贴进 SQL editor 的那一句 (只有校验串)
                                                         ② 填进 Vercel 连接串的密码 (只在这一次打到屏幕上, 不写文件)
  python3 scripts/workbench_role_password.py --stdin     不生成, 从标准输入读自己的密码 (只许字母和数字, 32 位以上)
  python3 scripts/workbench_role_password.py --selftest  用 RFC 7677 的例子核算法; 核密码规则 (CI python job 跑)

密码只用字母和数字: 别的字符 (/ # ? @ % : 等) 放进连接串要编码, 漏了编码连接串就解析失败。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import string
import sys

ROLE = "tv_workbench_ro"
ITERATIONS = 4096          # Postgres 自己算 SCRAM 时的默认轮数 (scram_iterations)
SALT_BYTES = 16
GEN_LEN = 40
MIN_LEN = 32
ALNUM = re.compile(r"[A-Za-z0-9]+")
VERIFIER = re.compile(r"SCRAM-SHA-256\$\d+:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+")


def _hmac(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _keys(password: str, salt: bytes, iterations: int) -> tuple[bytes, bytes, bytes]:
    """返回 (ClientKey, StoredKey, ServerKey)。只收字母数字, SASLprep 对它们是原样。"""
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("ascii"), salt, iterations)
    client_key = _hmac(salted, b"Client Key")
    return client_key, hashlib.sha256(client_key).digest(), _hmac(salted, b"Server Key")


def verifier(password: str, salt: bytes, iterations: int = ITERATIONS) -> str:
    _, stored, server = _keys(password, salt, iterations)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored)}:{b64(server)}"


def check_password(pw: str) -> str | None:
    """不合规就回一句为什么。"""
    if not ALNUM.fullmatch(pw):
        return "密码只许字母和数字 (别的字符放进连接串要编码, 漏了就连不上)"
    if len(pw) < MIN_LEN:
        return f"密码要 {MIN_LEN} 位以上"
    return None


def selftest() -> int:
    # RFC 7677 第 3 节的例子: 用户 user, 密码 pencil。算出的 ClientProof 和 ServerSignature 要和 RFC 一字不差。
    salt = base64.b64decode("W22ZaJ0SNY7soEsUEjb6gQ==")
    client_first_bare = "n=user,r=rOprNGfwEbeRWgbNEkqO"
    server_first = "r=rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0,s=W22ZaJ0SNY7soEsUEjb6gQ==,i=4096"
    client_final_wo_proof = "c=biws,r=rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0"
    auth = f"{client_first_bare},{server_first},{client_final_wo_proof}".encode("ascii")
    client_key, stored, server = _keys("pencil", salt, 4096)
    proof = bytes(a ^ b for a, b in zip(client_key, _hmac(stored, auth)))
    problems = []
    if base64.b64encode(proof).decode() != "dHzbZapWIk4jUhN+Ute9ytag9zjfMHgsqmmiz7AndVQ=":
        problems.append("ClientProof 和 RFC 7677 对不上")
    if base64.b64encode(_hmac(server, auth)).decode() != "6rriTRBi23WpRR/wtup+mMhUZUn/dB5nLTJRsjl95G4=":
        problems.append("ServerSignature 和 RFC 7677 对不上")
    v = verifier("pencil", salt, 4096)
    if not VERIFIER.fullmatch(v) or not v.startswith("SCRAM-SHA-256$4096:W22ZaJ0SNY7soEsUEjb6gQ==$"):
        problems.append(f"校验串的格式不对: {v[:40]}")
    for bad in ("a" * 31, "a" * 31 + "/", "a" * 31 + "#", "a" * 31 + "%", "a" * 31 + "@", "ä" * 40):
        if check_password(bad) is None:
            problems.append(f"不合规的密码没拦住 (长 {len(bad)})")
    gen = generate()
    if check_password(gen) is not None:
        problems.append("生成的密码自己不合规")
    if problems:
        print("workbench_role_password selftest: 红")
        for p in problems:
            print("  ✗ " + p)
        return 1
    print("workbench_role_password selftest: 过 (RFC 7677 的 ClientProof / ServerSignature 一致; 校验串格式; 密码只许字母数字、≥32 位)")
    return 0


def generate() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(GEN_LEN))


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    if "--stdin" in argv:
        pw = sys.stdin.readline().strip()
        why = check_password(pw)
        if why:
            print(why, file=sys.stderr)
            return 2
        shown = False
    else:
        pw = generate()
        shown = True
    stmt = f"ALTER ROLE {ROLE} PASSWORD '{verifier(pw, secrets.token_bytes(SALT_BYTES))}';"
    print("① 贴进 Supabase SQL editor 跑 (只有校验串, 没有明文):")
    print()
    print(stmt)
    print()
    if shown:
        print("② 填进 Vercel 的 WORKBENCH_DATABASE_URL 的密码 (只在这里打这一次; 别存进任何文件):")
        print()
        print(pw)
        print()
    print("连接串的样子 (连接池事务模式, 端口 6543):")
    print(f"  postgresql://{ROLE}.<项目 ref>:<上面的密码>@<连接池主机>:6543/postgres")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
