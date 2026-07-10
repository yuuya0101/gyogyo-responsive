import sqlite3
from pathlib import Path
from datetime import datetime
import html
import pandas as pd
import streamlit as st

try:
    import speech_recognition as sr
    SPEECH_AVAILABLE = True
except Exception:
    SPEECH_AVAILABLE = False


DB_PATH = Path("gyogyo_musen.db")

IMPORTANT_WORDS = {
    "重要": "重要連絡",
    "緊急": "緊急情報",
    "危険": "危険情報",
    "注意": "注意情報",
    "帰港": "帰港指示",
    "戻って": "帰港指示",
    "中止": "中止連絡",
    "変更": "変更連絡",
    "波": "気象・海象",
    "風": "気象・海象",
    "津波": "緊急情報",
    "救助": "緊急情報",
    "故障": "トラブル",
    "高波": "気象・海象",
    "濃霧": "気象・海象",
    "水揚げ": "作業連絡",
    "時間": "作業連絡",
}

DEFAULT_SHIPS = ["船A", "船B", "船C", "船D", "船E"]

MESSAGE_TEMPLATES = {
    "帰港連絡": "重要、波が高くなる予報のため早めに帰港してください。",
    "水揚げ時間変更": "連絡、水揚げ時間を13時から14時に変更します。",
    "注意喚起": "注意、風が強くなるため作業時は周囲を確認してください。",
    "作業中止": "緊急、天候悪化のため本日の作業を中止してください。",
    "自由入力": "",
}


def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        sender TEXT NOT NULL,
        message TEXT NOT NULL,
        tags TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_id INTEGER NOT NULL,
        ship_name TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        read_at TEXT,
        UNIQUE(log_id, ship_name)
    )
    """)

    for ship in DEFAULT_SHIPS:
        cur.execute("INSERT OR IGNORE INTO ships(name) VALUES(?)", (ship,))

    conn.commit()
    conn.close()


def detect_tags(text):
    tags = []
    for word, tag in IMPORTANT_WORDS.items():
        if word in text and tag not in tags:
            tags.append(tag)
    return tags


def is_important(tags_text):
    important_tags = ["重要連絡", "緊急情報", "危険情報", "帰港指示", "中止連絡"]
    return any(tag in str(tags_text) for tag in important_tags)


def highlight_text(text):
    for word in IMPORTANT_WORDS.keys():
        text = text.replace(word, f"**{word}**")
    return text


def highlight_text_html(text):
    safe_text = html.escape(str(text))
    for word in sorted(IMPORTANT_WORDS.keys(), key=len, reverse=True):
        safe_word = html.escape(word)
        safe_text = safe_text.replace(
            safe_word,
            f'<span class="keyword">{safe_word}</span>'
        )
    return safe_text


def tag_badges(tags_text):
    tags = [tag.strip() for tag in str(tags_text).split(",") if tag.strip()]
    if not tags:
        tags = ["通常"]

    badges = ""
    for tag in tags:
        css_class = "tag important-tag" if tag in ["重要連絡", "緊急情報", "危険情報", "帰港指示", "中止連絡"] else "tag"
        badges += f'<span class="{css_class}">{html.escape(tag)}</span>'
    return badges


def list_ships():
    conn = get_conn()
    df = pd.read_sql_query("SELECT name FROM ships ORDER BY name", conn)
    conn.close()
    return df["name"].tolist()


def add_ship(name):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO ships(name) VALUES(?)", (name,))
    conn.commit()
    conn.close()


def add_log(sender, message, target_ships):
    tags = detect_tags(message)
    tag_text = ", ".join(tags) if tags else "通常"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO logs(created_at, sender, message, tags) VALUES(?,?,?,?)",
        (now, sender, message, tag_text)
    )
    log_id = cur.lastrowid

    for ship in target_ships:
        cur.execute(
            "INSERT OR IGNORE INTO reads(log_id, ship_name, is_read, read_at) VALUES(?,?,0,NULL)",
            (log_id, ship)
        )

    conn.commit()
    conn.close()
    return log_id


def get_logs():
    conn = get_conn()
    logs_df = pd.read_sql_query(
        "SELECT * FROM logs ORDER BY id DESC",
        conn
    )
    conn.close()
    return logs_df


def get_log(log_id):
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT * FROM logs WHERE id=?",
        conn,
        params=(log_id,)
    )
    conn.close()
    if len(df) == 0:
        return None
    return df.iloc[0].to_dict()


def get_read_status(log_id):
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT ship_name, is_read, read_at FROM reads WHERE log_id=? ORDER BY ship_name",
        conn,
        params=(log_id,)
    )
    conn.close()
    return df


def mark_read(log_id, ship_name):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE reads SET is_read=1, read_at=? WHERE log_id=? AND ship_name=?",
        (now, log_id, ship_name)
    )
    conn.commit()
    conn.close()


def mark_unread(log_id, ship_name):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE reads SET is_read=0, read_at=NULL WHERE log_id=? AND ship_name=?",
        (log_id, ship_name)
    )
    conn.commit()
    conn.close()


def reset_demo_data():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM reads")
    cur.execute("DELETE FROM logs")
    conn.commit()
    conn.close()
    seed_sample_if_empty()


def recognize_from_microphone(seconds=5):
    if not SPEECH_AVAILABLE:
        st.error("SpeechRecognition または PyAudio がインストールされていません。")
        return ""

    recognizer = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            st.write("マイク調整中です...")
            recognizer.adjust_for_ambient_noise(source, duration=1)
            st.write(f"{seconds}秒間、音声を聞き取ります。話してください。")
            audio = recognizer.listen(source, phrase_time_limit=seconds)

        try:
            return recognizer.recognize_google(audio, language="ja-JP")
        except sr.UnknownValueError:
            return ""
        except sr.RequestError:
            st.error("音声認識サービスに接続できませんでした。")
            return ""
    except Exception as e:
        st.error(f"マイクの取得に失敗しました: {e}")
        return ""


def seed_sample_if_empty():
    logs = get_logs()
    if len(logs) == 0:
        ships = list_ships()
        sample1 = add_log(
            "漁協",
            "重要、波が高くなる予報のため早めに帰港してください。",
            ships
        )
        sample2 = add_log(
            "漁協",
            "連絡、水揚げ時間を13時から14時に変更します。",
            ships
        )
        mark_read(sample1, "船A")
        mark_read(sample1, "船C")
        mark_read(sample2, "船A")


def inject_css():
    """style.cssを読み込む。なければ最低限のCSSだけ適用する。"""
    css_path = Path("style.css")
    if css_path.exists():
        css = css_path.read_text(encoding="utf-8")
    else:
        css = """
        .stApp { background: #f3f8fa; }
        .hero { background: #0f4c5c; color: white; padding: 18px; border-radius: 18px; }
        .message-card { background: white; border-left: 8px solid #0f4c5c; padding: 15px; border-radius: 16px; margin: 12px 0; }
        .message-important { border-left-color: #d32f2f; background: #fff8f8; }
        .keyword { font-weight: 900; background: linear-gradient(transparent 55%, #ffe08a 55%); }
        """
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)




def show_header():
    st.markdown("""
    <div class="hero">
      <h1>📢 漁業連絡確認システム</h1>
      <p>漁協が送った連絡を、船が確認したか分かるアプリ</p>
    </div>
    <div class="flow">
      ① 漁協が送る　→　② 船が確認する　→　③ 漁協が確認状況を見る
    </div>
    """, unsafe_allow_html=True)


def show_guide(text):
    st.markdown(f'<div class="guide">{text}</div>', unsafe_allow_html=True)


def render_log_card(log, status_text=None):
    important_class = "message-important" if is_important(log["tags"]) else ""
    status_html = (
        f'<div class="sub">{html.escape(status_text)}</div>'
        if status_text else ""
    )

    card_html = (
        f'<div class="message-card {important_class}">'
        f'{status_html}'
        f'<div class="message-title">'
        f'ID:{html.escape(str(log["id"]))}　'
        f'{html.escape(str(log["sender"]))}'
        f'</div>'
        f'<div class="sub">'
        f'送信時刻：{html.escape(str(log["created_at"]))}'
        f'</div>'
        f'<div>{tag_badges(log["tags"])}</div>'
        f'<div class="message-body">'
        f'{highlight_text_html(log["message"])}'
        f'</div>'
        f'</div>'
    )

    st.markdown(card_html, unsafe_allow_html=True)

@st.fragment(run_every="3s")
def show_ship_messages(ship_name):
    """船側の連絡一覧を3秒ごとに自動更新する。"""
    conn = get_conn()
    ship_logs = pd.read_sql_query("""
        SELECT logs.id, logs.created_at, logs.sender, logs.message, logs.tags,
               reads.is_read, reads.read_at
        FROM logs
        JOIN reads ON logs.id = reads.log_id
        WHERE reads.ship_name=?
        ORDER BY logs.id DESC
    """, conn, params=(ship_name,))
    conn.close()

    st.caption("新着連絡を3秒ごとに自動確認しています。")

    if len(ship_logs) == 0:
        st.warning("自分宛ての連絡はありません。")
        return

    unread_count = int((ship_logs["is_read"] == 0).sum())
    st.metric("未確認の連絡", unread_count)

    only_unread = st.checkbox(
        "未確認だけ表示する",
        value=True,
        key=f"only_unread_{ship_name}"
    )
    if only_unread:
        ship_logs = ship_logs[ship_logs["is_read"] == 0]

    if len(ship_logs) == 0:
        st.success("未確認の連絡はありません。")
        return

    for _, row in ship_logs.iterrows():
        status = "✅ 確認済み" if row["is_read"] else "❌ 未確認"
        render_log_card(row, status)

        if row["is_read"]:
            st.success(f"確認済み：{row['read_at']}")
        else:
            if st.button(
                "確認しました",
                key=f"ship_read_{ship_name}_{row['id']}"
            ):
                mark_read(int(row["id"]), ship_name)
                st.success("確認済みにしました。漁協側にも反映されます。")
                st.rerun()


@st.fragment(run_every="3s")
def show_admin_status(selected_id):
    """漁協側の既読状況を3秒ごとに自動更新する。"""
    log = get_log(selected_id)
    if log is None:
        st.warning("選択した連絡が見つかりません。")
        return

    status_df = get_read_status(selected_id)
    st.caption("船の確認状況を3秒ごとに自動確認しています。")

    render_log_card(log)

    read_count = int(status_df["is_read"].sum()) if len(status_df) else 0
    total = len(status_df)
    unread_count = total - read_count

    col1, col2, col3 = st.columns(3)
    col1.metric("対象船", f"{total}")
    col2.metric("確認済み", f"{read_count}")
    col3.metric("未確認", f"{unread_count}")

    st.progress(0 if total == 0 else read_count / total)
    st.write("### 船別一覧")

    for _, row in status_df.iterrows():
        ship = row["ship_name"]
        is_read = bool(row["is_read"])
        read_at = row["read_at"]

        col_a, col_b, col_c = st.columns([2, 3, 3])

        with col_a:
            st.write(f"**{ship}**")

        with col_b:
            if is_read:
                st.success(f"確認済み：{read_at}")
            else:
                st.error("未確認")

        with col_c:
            if is_read:
                if st.button(
                    f"{ship}を未確認に戻す",
                    key=f"unread_{selected_id}_{ship}"
                ):
                    mark_unread(selected_id, ship)
                    st.rerun()
            else:
                if st.button(
                    f"{ship}を確認済みにする",
                    key=f"read_admin_{selected_id}_{ship}"
                ):
                    mark_read(selected_id, ship)
                    st.rerun()

    unread_ships = status_df[status_df["is_read"] == 0]["ship_name"].tolist()
    if unread_ships:
        st.warning("未確認：" + "、".join(unread_ships))
        if st.button(
            "未確認の船に再確認を促す",
            key=f"remind_{selected_id}"
        ):
            st.success("未確認の船に再確認を促しました。（プロトタイプ表示）")
    else:
        st.success("全ての船が確認済みです。")


st.set_page_config(page_title="漁業連絡確認システム", page_icon="📢", layout="wide")
inject_css()
init_db()
seed_sample_if_empty()

show_header()

with st.expander("使い方を確認する"):
    st.write("""
    1. **漁協側：連絡を送る** で連絡を送信する  
    2. **船側：連絡を確認する** で船を選び、「確認しました」を押す  
    3. **漁協側：確認状況を見る** で確認済み・未確認を確認する  
    """)

mode = st.sidebar.radio(
    "画面を選択",
    [
        "漁協側：連絡を送る",
        "船側：連絡を確認する",
        "漁協側：確認状況を見る",
        "設定",
        "発表用まとめ",
    ]
)

ships = list_ships()


if mode == "漁協側：連絡を送る":
    st.header("① 漁協側：連絡を送る")
    show_guide("<b>ここでやること：</b>漁協側が船に向けて連絡を送ります。送った連絡は船側画面に表示されます。")

    input_type = st.radio("入力方法", ["手入力", "マイク認識"], horizontal=True)

    sender = st.selectbox("送信元", ["漁協", "船A", "船B", "船C", "その他"])
    target_ships = st.multiselect("対象船", ships, default=ships)

    if input_type == "手入力":
        template_name = st.selectbox("テンプレート", list(MESSAGE_TEMPLATES.keys()))
        message = st.text_area(
            "連絡内容",
            value=MESSAGE_TEMPLATES[template_name],
            placeholder="例：重要、波が高くなる予報のため早めに帰港してください。",
            height=130,
        )

        tags = detect_tags(message)
        st.info(f"自動タグ：{', '.join(tags) if tags else '通常'}")

        if st.button("連絡を送信・記録する"):
            if not message.strip():
                st.warning("連絡内容を入力してください。")
            elif len(target_ships) == 0:
                st.warning("対象船を選んでください。")
            else:
                log_id = add_log(sender, message.strip(), target_ships)
                st.success(f"連絡を記録しました。次は船側で確認できます。連絡ID：{log_id}")
                st.rerun()

    else:
        if not SPEECH_AVAILABLE:
            st.warning("音声認識ライブラリが読み込めません。手入力を使用してください。")

        seconds = st.slider("聞き取る秒数", 3, 15, 5)

        if st.button("マイクで聞き取って送信"):
            text = recognize_from_microphone(seconds)
            if text:
                st.success("音声を認識しました。")
                st.write(f"認識結果：{text}")
                log_id = add_log(sender, text, target_ships)
                st.success(f"連絡を記録しました。連絡ID：{log_id}")
            else:
                st.warning("音声を認識できませんでした。")


elif mode == "船側：連絡を確認する":
    st.header("② 船側：自分宛ての連絡を確認する")
    show_guide("<b>ここでやること：</b>船側の人が連絡を見て、「確認しました」を押します。")

    ship_name = st.selectbox("自分の船を選択", ships)
    show_ship_messages(ship_name)


elif mode == "漁協側：確認状況を見る":
    st.header("③ 漁協側：船ごとの確認状況")
    show_guide("<b>ここでやること：</b>漁協側が、どの船が確認済みでどの船が未確認なのかを確認します。")

    logs_df = get_logs()
    if len(logs_df) == 0:
        st.warning("まだ連絡ログがありません。")
    else:
        selected_id = st.selectbox(
            "連絡を選択",
            logs_df["id"].tolist(),
            format_func=lambda x: f"ID:{x} " + logs_df[logs_df["id"] == x]["message"].iloc[0][:35]
        )
        show_admin_status(selected_id)


elif mode == "設定":
    st.header("設定")

    st.subheader("船の追加")
    new_ship = st.text_input("追加する船名", placeholder="例：船F")
    if st.button("船を追加"):
        if not new_ship.strip():
            st.warning("船名を入力してください。")
        else:
            add_ship(new_ship.strip())
            st.success(f"{new_ship.strip()}を追加しました。")
            st.rerun()

    st.subheader("登録船一覧")
    st.write("、".join(list_ships()))

    st.subheader("デモデータ")
    if st.button("デモデータを初期状態に戻す"):
        reset_demo_data()
        st.success("デモデータを初期状態に戻しました。")
        st.rerun()

    st.subheader("CSV出力")
    logs_df = get_logs()
    if len(logs_df) > 0:
        csv = logs_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "連絡ログCSVをダウンロード",
            data=csv,
            file_name="logs.csv",
            mime="text/csv"
        )


elif mode == "発表用まとめ":
    st.header("発表用まとめ")
    st.markdown("""
### テーマ
**漁業連絡確認システム**

### 課題
船上ではエンジン音、波、風、作業音などで、無線や口頭の連絡を聞き逃すことがあります。  
また、漁協側はどの船が連絡を確認したか分かりにくいという課題があります。

### 解決方法
漁協が連絡を送ると、船側の画面に連絡が表示されます。  
船側が **「確認しました」** を押すと、漁協側の画面で **確認済み** として表示されます。

### このプロトタイプで見せること
1. 漁協側で連絡を送る  
2. 船側で連絡を確認する  
3. 船側が「確認しました」を押す  
4. 漁協側で確認済み・未確認を確認する  

### 今後の拡張
今後はスマホ通知やスマートウォッチ通知に対応させることで、作業中でも重要連絡に気づきやすくできます。
""")
