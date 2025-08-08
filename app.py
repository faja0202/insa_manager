import os
from datetime import timedelta
from threading import Lock

import pandas as pd
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, abort
)
from flask_login import (
    LoginManager, UserMixin,
    login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

# ---------- 기본 설정 ----------
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_FILENAME = "insa_DB.xlsx"  # 실제 엑셀 파일명
EXCEL_PATH = os.path.join(APP_ROOT, DB_FILENAME)
IP_WHITELIST = set()
EXCEL_LOCK = Lock()

# 면담 기록 업로드 폴더
UPLOAD_FOLDER = os.path.join(APP_ROOT, 'static', 'uploads', 'interviews')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))
app.permanent_session_lifetime = timedelta(minutes=40)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ---------- 데이터 로드 헬퍼 ----------
def load_df():
    """
    Thread-safe하게 엑셀을 읽어 pandas DataFrame을 반환합니다.
    """
    with EXCEL_LOCK:
        return pd.read_excel(EXCEL_PATH, engine="openpyxl", dtype=str).fillna("")

# ---------- IP 화이트리스트 설정 ----------
# (모듈 최상단에 한 번만 정의)
IP_WHITELIST = {
    "127.0.0.1",       # 로컬
    "192.168.0.10",    # 사내망
    "203.0.113.45",    # 허용 외부 IP
    "121.190.230.110"  # 정주영 ip
    "121.171.120.123" #스트롱 룸 ip
}

# ---------- IP 화이트리스트 체크 ----------
@app.before_request
def check_ip_whitelist():
    # 1) static 파일 로드, 2) 차단 페이지 자체는 예외
    if request.endpoint in ("static", "ip_block"):
        return  # 여기만 건너뛰고 나머지—login 포함—모두 체크

    client_ip = request.remote_addr or ""

    # 화이트리스트가 비어 있지 않고, client_ip가 목록에 없으면 차단
    if IP_WHITELIST and client_ip not in IP_WHITELIST:
        # 접근 시도 로그 남기기 (선택)
        app.logger.warning(f"Blocked IP {client_ip} accessing {request.path}")
        return redirect(url_for("ip_block"))

# ---------- 차단 페이지 ----------
@app.route("/ip_block")
def ip_block():
    return render_template("ip_block.html"), 403

# ---------- Flask-Login 설정 ----------
login_manager = LoginManager(app)
login_manager.login_view = "login"

@login_manager.unauthorized_handler
def handle_needs_login():
    flash("로그인이 필요합니다.", "warning")
    return redirect(url_for("login", next=request.url))

# ---------- 단일 관리자 계정 예시 ----------
ADMIN_USER = "admin"
ADMIN_PW_HASH = generate_password_hash("1234")

class User(UserMixin):
    def __init__(self, id_):
        self.id = id_

@login_manager.user_loader
def load_user(user_id):
    return User(user_id) if user_id == ADMIN_USER else None

# ---------- 로그인 / 로그아웃 ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username != ADMIN_USER:
            flash("존재하지 않는 사용자명입니다.", "danger")
        elif not check_password_hash(ADMIN_PW_HASH, password):
            flash("비밀번호가 올바르지 않습니다.", "danger")
        else:
            login_user(User(username))
            flash(f"{username}님, 환영합니다!", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("main"))

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for("login"))

# ---------- 메인 ----------
@app.route("/", methods=["GET"])
@login_required
def main():
    return render_template("main.html")

@app.route("/employees", methods=["GET"])
@login_required
def employee_list():
    # ① 원하는 팀 출력 순서
    team_order = ['테스트팀', '경영지원팀', '플랫폼솔루션개발팀', '센터']

    # ② 엑셀 읽기
    with EXCEL_LOCK:
        df = pd.read_excel(EXCEL_PATH, engine="openpyxl", dtype=str).fillna("")

    # ③ extension_number 컬럼 보장
    if 'extension_number' not in df.columns:
        df['extension_number'] = ""

    # ④ 화면용 컬럼만 추출
    subset = df[['name', 'team_name', 'position', 'extension_number', 'mbti']]
    records = subset.to_dict(orient="records")

    # ⑤ 팀 순서대로 정렬
    priority = {team: idx for idx, team in enumerate(team_order)}
    default_priority = len(team_order)
    records_sorted = sorted(
        records,
        key=lambda emp: priority.get(emp['team_name'], default_priority)
    )

    # ⑥ 실제로 출력된 팀 이름 순서(중복 제거)
    teams_seen = []
    for emp in records_sorted:
        t = emp['team_name']
        if t not in teams_seen:
            teams_seen.append(t)

    # ⑦ 순서 리스트에 없는 팀만 골라내기
    other_teams = [t for t in teams_seen if t not in team_order]

    # ⑧ 템플릿으로 전달
    return render_template(
        "employee_list.html",
        employees=records_sorted,
        team_order=team_order,
        other_teams=other_teams
    )


# ---------- 직원 상세 ----------
@app.route("/employees/<string:name>", methods=["GET", "POST"])
@login_required
def employee_detail(name):
    df = load_df()
    if name not in df['name'].values:
        abort(404, description="해당 직원을 찾을 수 없습니다.")

    if request.method == "POST":
        for col in df.columns:
            if col in request.form:
                df.loc[df['name'] == name, col] = request.form[col]
        with EXCEL_LOCK:
            df.to_excel(EXCEL_PATH, index=False, engine="openpyxl")
        flash("수정사항이 저장되었습니다.", "success")
        return redirect(url_for("employee_detail", name=name))

    emp_data = df.loc[df['name'] == name].iloc[0].to_dict()
    return render_template("employee_detail.html", employee=emp_data)

# ---------- 직원 검색 ----------
@app.route("/employee_search")
@login_required
def employee_search():
    q = request.args.get('q', '').strip()
    df = load_df()
    if q:
        filtered = df[df['name'].str.contains(q, case=False, na=False)]
    else:
        filtered = df
    records = filtered[['name','team_name','position','phone_number','mbti']].to_dict(orient='records')
    return render_template("employee_list.html", employees=records)

# ---------- 면담 기록 ----------
@app.route("/interview_records", methods=["GET", "POST"])
@login_required
def interview_records():
    if request.method == 'POST':
        file = request.files.get('record')
        if file:
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(save_path)
            flash("면담기록이 업로드되었습니다.", "success")
        return redirect(url_for('interview_records'))
    files = os.listdir(app.config['UPLOAD_FOLDER'])
    return render_template("interview_records.html", records=files)

# ---------- 인사정보 페이지 ----------
@app.route("/profile")
@login_required
def profile():
    # 추후 상세 프로필 페이지로 연결 예정
    return redirect(url_for("employee_list"))

# ---------- 앱 실행 ----------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)