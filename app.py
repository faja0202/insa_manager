# app.py (주석 강화 & 안전성/UX 개선)
# ─────────────────────────────────────────────────────────────────────
# 주요 변경 요약
# 1) 엑셀 로드 시 상세 화면에서 쓰는 모든 컬럼 자동 보강(_ensure_all_columns)
# 2) 직원 목록 서버사이드 검색(q 파라미터) 지원
# 3) IP 화이트리스트 예외에 'login' 추가 (차단 페이지→로그인 허용)
# 4) 엑셀 저장 시 임시파일→원본 교체(atomic write)
# 5) 대시보드 지표 제공(_dashboard_context): 직원 수 / DB 수정시각 / 최근 변경 / 최종 수정자
# 6) 세션 보안 쿠키/템플릿 재로딩 옵션 보강
# 7) 미디어 라우트 분리: 이력서(resume) + 사진(photo) 보호 디렉터리 제공
# 8) (신설) 변경 로그(change_log.jsonl) 기록/조회: 최근 변경 사항 카드에 표시, 최종 수정자/시각 산출
# ─────────────────────────────────────────────────────────────────────

# ============================
# [STD LIB]
# ============================
import os
import re
import json
from datetime import datetime, timedelta
from threading import Lock
from pathlib import Path
from typing import Set, Dict, List

# ============================
# [3RD PARTY]
# ============================
import pandas as pd
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, abort, send_file
)
from flask_login import (
    LoginManager, UserMixin,
    login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import NotFound

# ============================
# [CONFIG] Paths & Globals
# ============================
APP_ROOT: Path = Path(__file__).resolve().parent

# DB는 private/db/insa_DB.xlsx 로 관리
DB_DIR: Path = APP_ROOT / "private" / "db"
DB_DIR.mkdir(parents=True, exist_ok=True)                     # 폴더 없으면 생성
DB_FILENAME: str = os.getenv("DB_FILENAME", "insa_DB.xlsx")
EXCEL_PATH: Path = DB_DIR / DB_FILENAME
EXCEL_LOCK = Lock()

# 변경 로그(최근 변경 사항 카드/최종 수정자 표시용)
LOG_PATH: Path = DB_DIR / "change_log.jsonl"

# 상세 화면(UI)에서 사용하는 모든 컬럼(누락 시 자동 추가)
ALL_EMP_FIELDS: List[str] = [
    # 기본
    "name", "team_name", "position", "extension_number", "phone_number",
    "mbti", "birthdate", "hire_date", "exit_date", "salary",
    # 상세
    "ssn", "emergency_contact", "strong_type", "firo_i", "firo_c", "firo_a",
    "internal_training", "email", "exit_reason",
    "address", "major", "degree", "thesis",
    "work_history", "certification", "discipline_awards", "recent_projects",
    "ceo_meeting_notes", "notes",
]

# 최초 생성 시 최소 기본 컬럼
EMP_BASE_COLS = [
    "name", "team_name", "position", "extension_number", "phone_number",
    "mbti", "birthdate", "hire_date", "exit_date", "salary"
]

# 보호 영역(정적 미공개) 파일 경로
RESUME_DIR: Path = APP_ROOT / "private" / "resume"
RESUME_DIR.mkdir(parents=True, exist_ok=True)
PHOTO_DIR: Path = APP_ROOT / "private" / "photo"
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

# IP 화이트리스트(비어있으면 기능 비활성)
IP_WHITELIST: Set[str] = set()
_raw_ips = os.getenv("IP_WHITELIST", "").strip()
if _raw_ips:
    IP_WHITELIST |= {ip.strip() for ip in _raw_ips.split(",") if ip.strip()}

# ============================
# [APP INIT]
# ============================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or os.urandom(24)  # 개발용 랜덤 키
app.permanent_session_lifetime = timedelta(minutes=int(os.getenv("SESSION_MINUTES", "40")))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(os.getenv("SESSION_COOKIE_SECURE", "0") == "1"),
    TEMPLATES_AUTO_RELOAD=(os.getenv("FLASK_DEBUG", "0") == "1"),
)

# ============================
# [DATA ACCESS] Excel helpers
# ============================
def _ensure_excel_exists() -> None:
    """엑셀 파일이 없으면 최소 기본 컬럼으로 생성."""
    if not EXCEL_PATH.exists():
        with EXCEL_LOCK:
            df = pd.DataFrame(columns=EMP_BASE_COLS)
            df.to_excel(EXCEL_PATH, index=False, engine="openpyxl")

def _ensure_all_columns(df: pd.DataFrame) -> pd.DataFrame:
    """UI가 요구하는 컬럼이 엑셀에 없으면 빈 문자열로 추가."""
    for col in ALL_EMP_FIELDS:
        if col not in df.columns:
            df[col] = ""
    return df

def load_df() -> pd.DataFrame:
    """엑셀을 로드하여 문자열형으로 전달. 결측치는 빈 문자열."""
    _ensure_excel_exists()
    with EXCEL_LOCK:
        df = pd.read_excel(EXCEL_PATH, engine="openpyxl", dtype=str).fillna("")
    return _ensure_all_columns(df)

def save_df(df: pd.DataFrame) -> None:
    """
    엑셀 저장(락 포함).
    - 안정성: 임시파일로 먼저 저장 후 원본 교체(atomic write).
    """
    with EXCEL_LOCK:
        tmp_path = EXCEL_PATH.with_suffix(".tmp.xlsx")
        df.to_excel(tmp_path, index=False, engine="openpyxl")
        os.replace(tmp_path, EXCEL_PATH)

# ============================
# [CHANGE LOG] 기록/조회 유틸
# ============================
def _diff_row(old: Dict[str, str], new: Dict[str, str]) -> List[Dict[str, str]]:
    """행 단위 변경점 계산(name 제외)."""
    diffs: List[Dict[str, str]] = []
    keys = set(old.keys()) | set(new.keys())
    for k in keys:
        if k == "name":
            continue
        ov = (old.get(k, "") or "").strip()
        nv = (new.get(k, "") or "").strip()
        if ov != nv:
            diffs.append({"field": k, "old": ov, "new": nv})
    return diffs

def _append_change_log(employee: str, user: str, changes: List[Dict[str, str]]) -> None:
    """변경 로그 한 줄(JSONL) 추가."""
    if not changes:
        return
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "employee": employee,
        "user": user or "-",
        "changes": changes,
    }
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # 로그 실패는 서비스 중단 사유 아님
        pass

def _read_recent_changes(max_items: int = 10) -> List[Dict[str, object]]:
    """최근 N개 변경 로그(신규순) 반환."""
    items: List[Dict[str, object]] = []
    if not LOG_PATH.exists():
        return items
    try:
        with LOG_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()[-max_items:]
        # 최신순 정렬 위해 역순
        for line in reversed(lines):
            try:
                d = json.loads(line)
                items.append({
                    "employee": d.get("employee", ""),
                    "owner": d.get("user", "-"),
                    "updated_at": d.get("ts", ""),
                    "changes": d.get("changes", []),
                })
            except Exception:
                continue
    except Exception:
        pass
    return items

# ============================
# [UTILS] 날짜/연봉 정규화
# ============================
def to_iso_date(val: str) -> str:
    # 다양한 포맷 → YYYY-MM-DD
    if val is None:
        return ""
    s = str(val).strip()
    if s == "" or s.lower() == "nan":
        return ""
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    s = s.replace(".", "-").replace("/", "-")
    if re.fullmatch(r"\d{8}", s):
        try:
            return datetime(int(s[:4]), int(s[4:6]), int(s[6:8])).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    if re.fullmatch(r"\d{6}", s):
        yy, mm, dd = int(s[:2]), int(s[2:4]), int(s[4:6])
        year = 2000 + yy if yy <= 69 else 1900 + yy
        try:
            return datetime(year, mm, dd).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    try:
        d = pd.to_datetime(s, errors="coerce")
        return "" if pd.isna(d) else d.strftime("%Y-%m-%d")
    except Exception:
        return ""

def normalize_salary(val: str) -> str:
    """
    급여 입력을 숫자 문자열로 통일.
    - '만' 단위, 쉼표 등 제거
    """
    if val is None:
        return ""
    s = str(val).strip()
    if s == "" or s.lower() == "nan":
        return ""
    raw = s.replace(",", "").replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)", raw)
    if not m:
        return ""
    num = float(m.group(1))
    if "만" in raw:
        return str(int(round(num * 10000)))
    if "원" in raw or num >= 100000:
        return str(int(round(num)))
    if len(str(int(num))) >= 5:
        return str(int(round(num)))
    return str(int(round(num * 10000)))

# ============================
# [SECURITY] IP Whitelist
# ============================
EXEMPT_IP_ENDPOINTS = {"static", "ip_block", "login"}  # 로그인은 예외

@app.before_request
def check_ip_whitelist():
    """
    허용 IP가 설정되어 있으면, 예외 엔드포인트를 제외하고 접근 차단.
    """
    if not request.endpoint or request.endpoint in EXEMPT_IP_ENDPOINTS:
        return
    client_ip = (request.remote_addr or "").strip()
    if IP_WHITELIST and client_ip not in IP_WHITELIST:
        app.logger.warning(f"Blocked IP {client_ip} accessing {request.path}")
        return redirect(url_for("ip_block"), code=303)

@app.route("/ip_block")
def ip_block():
    return render_template("ip_block.html"), 403

# ============================
# [AUTH] Flask-Login
# ============================
login_manager = LoginManager(app)
login_manager.login_view = "login"

@login_manager.unauthorized_handler
def handle_needs_login():
    flash("로그인이 필요합니다.", "warning")
    return redirect(url_for("login", next=request.url))

# 개발 간편 계정(운영 전환 권장)
ADMIN_USERS_INLINE: Dict[str, str] = {
    "admin": "1234",
    "assesta": "0820",
}
USERS: Dict[str, str] = {u: generate_password_hash(pw) for u, pw in ADMIN_USERS_INLINE.items()}

class User(UserMixin):
    def __init__(self, id_: str):
        self.id = id_
    @property
    def username(self) -> str:
        # 템플릿에서 {{ current_user.username }}로 접근 가능하도록
        return self.id

@login_manager.user_loader
def load_user(user_id: str):
    return User(user_id) if user_id in USERS else None

# ============================
# [ROUTES] 로그인
# ============================
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        pw_hash = USERS.get(username)
        if not pw_hash:
            flash("존재하지 않는 사용자명입니다.", "danger")
        elif not check_password_hash(pw_hash, password):
            flash("비밀번호가 올바르지 않습니다.", "danger")
        else:
            login_user(User(username))
            flash(f"{username}님, 환영합니다!", "success")
            next_page = request.values.get("next")
            return redirect(next_page or url_for("main"))
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for("login"))

# ============================
# [HELPER] 대시보드 컨텍스트
# ============================
def _dashboard_context():
    """
    main.html에서 사용하는 지표/목록 제공.
    - employee_count: 직원 수
    - db_last_modified: 최종 수정 시각(로그 기준, 없으면 파일 mtime)
    - db_last_modifier: 최종 수정자(로그 기준)
    - recent_changes: 최근 변경 로그(최신순)
    """
    ctx = {}
    # 직원 수
    try:
        df = load_df()
        ctx["employee_count"] = int(df.shape[0])
    except Exception:
        ctx["employee_count"] = "-"

    # 최근 변경 로그
    recent_changes = _read_recent_changes(max_items=10)
    ctx["recent_changes"] = recent_changes

    # 최종 수정자/시각
    if recent_changes:
        ctx["db_last_modifier"] = recent_changes[0].get("owner", "-")
        ctx["db_last_modified"] = recent_changes[0].get("updated_at", "-")
    else:
        # 로그 없으면 파일 mtime 기준
        try:
            mtime = datetime.fromtimestamp(EXCEL_PATH.stat().st_mtime)
            ctx["db_last_modified"] = mtime.strftime("%Y-%m-%d %H:%M")
        except Exception:
            ctx["db_last_modified"] = "-"
        ctx["db_last_modifier"] = "-"

    return ctx

# ============================
# [ROUTES] 메인 & 직원 목록
# ============================
@app.route("/", methods=["GET"])
@login_required
def main():
    return render_template("main.html", **_dashboard_context())

@app.route("/employees", methods=["GET"])
@login_required
def employee_list():
    """
    직원 목록 화면
    - team_order 우선 정렬
    - q 파라미터로 서버사이드 간단 검색
    """
    team_order = ["테스트팀", "경영지원팀", "플랫폼솔루션개발팀", "센터"]
    df = load_df()

    if "extension_number" not in df.columns:
        df["extension_number"] = ""

    subset = df[["name", "team_name", "position", "extension_number", "mbti"]].copy()

    q = (request.args.get("q", "") or "").strip().lower()
    if q:
        mask = subset.apply(lambda row: any(q in str(v).lower() for v in row.values), axis=1)
        subset = subset[mask]

    records = subset.to_dict(orient="records")

    priority = {team: idx for idx, team in enumerate(team_order)}
    default_priority = len(team_order)
    records_sorted = sorted(records, key=lambda emp: priority.get(emp.get("team_name", ""), default_priority))

    teams_seen = []
    for emp in records_sorted:
        t = emp.get("team_name", "")
        if t and t not in teams_seen:
            teams_seen.append(t)
    other_teams = [t for t in teams_seen if t not in team_order]

    return render_template(
        "employee_list.html",
        employees=records_sorted,
        team_order=team_order,
        other_teams=other_teams,
        query=q,
    )

# ============================
# [ROUTES] 직원 상세
# ============================
@app.route("/employees/<string:name>", methods=["GET", "POST"])
@login_required
def employee_detail(name: str):
    df = load_df()
    if "name" not in df.columns or name not in df["name"].values:
        abort(404, description="해당 직원을 찾을 수 없습니다.")

    DATE_FIELDS_IN_FORM = {"birthdate", "hire_date", "exit_date"}

    if request.method == "POST":
        mask = df["name"] == name

        # 변경 전 스냅샷(로그용)
        before = df.loc[mask].iloc[0].to_dict()

        # 반영
        for form_key in request.form:
            if form_key == "name":  # 이름은 식별자, 변경 금지
                continue
            value = request.form.get(form_key, "").strip()
            if form_key in DATE_FIELDS_IN_FORM:
                value = to_iso_date(value)
            if form_key == "salary":
                value = normalize_salary(value)
            if form_key not in df.columns:
                df[form_key] = ""
            df.loc[mask, form_key] = value

        # 저장
        save_df(df)

        # 변경 후 스냅샷 및 변경 로그 기록
        after = df.loc[mask].iloc[0].to_dict()
        diffs = _diff_row(before, after)
        _append_change_log(employee=name, user=(current_user.id if current_user.is_authenticated else "-"), changes=diffs)

        flash("수정사항이 저장되었습니다.", "success")
        return redirect(url_for("employee_detail", name=name), code=303)

    # GET: 표시 데이터 가공
    row = df.loc[df["name"] == name].iloc[0].to_dict()
    for k, v in list(row.items()):
        v = "" if pd.isna(v) else str(v)
        if k == "extension_number":
            v = re.sub(r"\.0$", "", v)  # 엑셀 float 꼬리 제거
        row[k] = v
    row["birthdate"] = to_iso_date(row.get("birthdate", ""))
    row["hire_date"]  = to_iso_date(row.get("hire_date", ""))
    row["exit_date"]  = to_iso_date(row.get("exit_date", ""))
    row["salary"]     = normalize_salary(row.get("salary", ""))

    return render_template("employee_detail.html", employee=row)

# ============================
# [ROUTES] Media: Resume / Photo
# ============================
def _resume_path(name: str) -> Path:
    """
    이름 기반 PDF 경로(디렉터리 탈출 방지).
    - private/resume/<name>.pdf
    """
    p = (RESUME_DIR / f"{name}.pdf").resolve()
    if not str(p).startswith(str(RESUME_DIR.resolve())) or p.suffix.lower() != ".pdf":
        raise NotFound()
    return p

@app.route("/employees/<name>/resume/view", endpoint="resume_view")
@login_required
def resume_view(name: str):
    """
    이력서 PDF 반환. (없으면 404)
    필요 시 default.pdf 대체로 변경 가능.
    """
    try:
        fp = _resume_path(name)
        if not fp.exists():
            raise NotFound()
        return send_file(
            str(fp),
            mimetype="application/pdf",
            as_attachment=False,
            download_name=fp.name,
            conditional=True,
        )
    except NotFound:
        abort(404)

def _photo_path(name: str) -> Path:
    """
    이름 기반 PNG 경로(디렉터리 탈출 방지).
    - private/photo/<name>.png
    """
    p = (PHOTO_DIR / f"{name}.png").resolve()
    if not str(p).startswith(str(PHOTO_DIR.resolve())) or p.suffix.lower() != ".png":
        raise NotFound()
    return p

@app.route("/employees/<name>/photo", endpoint="photo_view")
@login_required
def photo_view(name: str):
    """
    직원 사진 PNG 반환. 없으면 default.png로 대체.
    - 기본 이미지: private/photo/default.png
    """
    try:
        fp = _photo_path(name)
        if not fp.exists():
            fp = (PHOTO_DIR / "default.png").resolve()
            if not fp.exists():
                raise NotFound()
        return send_file(
            str(fp),
            mimetype="image/png",
            as_attachment=False,
            download_name=fp.name,
            conditional=True,
        )
    except NotFound:
        abort(404)

# ============================
# [ENTRYPOINT]
# ============================
if __name__ == "__main__":
    app.run(
        debug=(os.getenv("FLASK_DEBUG", "0") == "1"),
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000"))
    )
