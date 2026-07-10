import sqlite3
import io
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


def apply_message_template():
    """テンプレート変更時に連絡内容へ反映する。"""
    template_name = st.session_state.get("send_template", "自由入力")
    st.session_state["send_message"] = MESSAGE_TEMPLATES.get(template_name, "")


def reset_send_form():
    """次回の再実行時に送信フォームを初期化する予約を行う。"""
    # Streamlitでは、画面に表示済みのウィジェットと同じキーを
    # ボタン処理の途中で直接変更すると例外になるため、ここでは予約だけ行う。
    st.session_state["send_form_reset_pending"] = True


def apply_pending_send_form_reset():
    """ウィジェット生成前に、予約されたフォーム初期化を実行する。"""
    if st.session_state.pop("send_form_reset_pending", False):
        st.session_state["send_targets"] = []
        st.session_state["send_template"] = "自由入力"
        st.session_state["send_message"] = ""
        st.session_state["voice_transcript"] = ""
        st.session_state["voice_audio_version"] = (
            st.session_state.get("voice_audio_version", 0) + 1
        )


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


def transcribe_recorded_audio(uploaded_audio):
    """ブラウザで録音されたWAV音声を日本語テキストへ変換する。"""
    if not SPEECH_AVAILABLE:
        st.error("音声認識ライブラリを読み込めませんでした。")
        return ""

    try:
        audio_bytes = uploaded_audio.getvalue()
        recognizer = sr.Recognizer()

        with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
            audio_data = recognizer.record(source)

        return recognizer.recognize_google(audio_data, language="ja-JP")

    except sr.UnknownValueError:
        st.warning("音声を聞き取れませんでした。周囲が静かな場所でもう一度録音してください。")
        return ""
    except sr.RequestError:
        st.error("音声認識サービスに接続できませんでした。時間をおいて再度お試しください。")
        return ""
    except Exception as exc:
        st.error(f"音声の変換に失敗しました：{exc}")
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


def inject_css(theme):
    """選択された表示テーマのCSSを読み込む。"""
    css_name = "style_dark.css" if theme == "ダーク" else "style_light.css"
    css_path = Path(css_name)

    if not css_path.exists():
        css_path = Path("style.css")

    if css_path.exists():
        css = css_path.read_text(encoding="utf-8")
    else:
        css = """
        .stApp { background: #f6f8fb; color: #1f2937; }
        .hero { background: #ffffff; padding: 24px; border: 1px solid #e5e7eb; }
        """

    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

def show_header():
    st.markdown("""
    <div class="hero">
      <h1>漁業連絡管理システム</h1>
      <p>漁協と船舶の連絡、および確認状況を一元管理します。</p>
    </div>
    <div class="flow">
      連絡作成　／　船側確認　／　確認状況
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
        status = "確認済み" if row["is_read"] else "未確認"
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


st.set_page_config(page_title="漁業連絡管理システム", layout="wide")

init_db()
seed_sample_if_empty()

st.sidebar.markdown("### 表示設定")
theme = st.sidebar.radio(
    "テーマ",
    ["ライト", "ダーク"],
    horizontal=True,
    key="display_theme",
)
inject_css(theme)

show_header()

with st.expander("操作方法"):
    st.write("""
    - **連絡作成**で船舶への連絡を登録します。  
    - **船側確認**で対象船を選び、確認済みにします。  
    - **確認状況**で船ごとの確認状況を確認します。  
    """)

mode = st.sidebar.radio(
    "画面を選択",
    [
        "連絡作成",
        "船側確認",
        "確認状況",
        "システム設定",
        "システム概要",
    ]
)

ships = list_ships()


if mode == "連絡作成":
    st.header("連絡作成")
    show_guide("<b>概要：</b>対象船を選択し、連絡内容を登録します。登録した連絡は船側画面に反映されます。")

    # 送信後の通知は再読み込み後も1回だけ表示する
    send_notice = st.session_state.pop("send_notice", None)
    if send_notice:
        st.success(
            f"連絡を送信しました。連絡ID：{send_notice['log_id']}　"
            f"送信先：{'、'.join(send_notice['targets'])}"
        )
        st.caption("入力欄を初期化しました。続けて新しい連絡を作成できます。")

    # 初期値
    if "send_input_type" not in st.session_state:
        st.session_state["send_input_type"] = "手入力"
    if "send_sender" not in st.session_state:
        st.session_state["send_sender"] = "漁協"
    if "send_targets" not in st.session_state:
        st.session_state["send_targets"] = ships.copy()
    if "send_template" not in st.session_state:
        st.session_state["send_template"] = "帰港連絡"
    if "send_message" not in st.session_state:
        st.session_state["send_message"] = MESSAGE_TEMPLATES["帰港連絡"]
    if "voice_transcript" not in st.session_state:
        st.session_state["voice_transcript"] = ""
    if "voice_audio_version" not in st.session_state:
        st.session_state["voice_audio_version"] = 0

    # 送信後の初期化は、各入力ウィジェットを作る前に行う。
    apply_pending_send_form_reset()

    input_type = st.radio(
        "入力方法",
        ["手入力", "マイク認識"],
        horizontal=True,
        key="send_input_type",
    )

    sender = st.selectbox(
        "送信元",
        ["漁協", "船A", "船B", "船C", "その他"],
        key="send_sender",
    )
    target_ships = st.multiselect(
        "対象船",
        ships,
        key="send_targets",
        placeholder="送信する船を選択してください",
    )

    if input_type == "手入力":
        st.selectbox(
            "テンプレート",
            list(MESSAGE_TEMPLATES.keys()),
            key="send_template",
            on_change=apply_message_template,
        )
        message = st.text_area(
            "連絡内容",
            key="send_message",
            placeholder="例：重要、波が高くなる予報のため早めに帰港してください。",
            height=130,
        )

        tags = detect_tags(message)
        st.info(f"自動タグ：{', '.join(tags) if tags else '通常'}")

        if st.button("連絡を送信・記録する", type="primary"):
            if not message.strip():
                st.warning("連絡内容を入力してください。")
            elif len(target_ships) == 0:
                st.warning("対象船を選んでください。")
            else:
                sent_targets = target_ships.copy()
                log_id = add_log(sender, message.strip(), sent_targets)
                st.session_state["send_notice"] = {
                    "log_id": log_id,
                    "targets": sent_targets,
                }
                reset_send_form()
                st.rerun()

    else:
        st.caption(
            "スマートフォンのマイクで録音し、文字に変換してから内容を確認して送信します。"
        )

        if not SPEECH_AVAILABLE:
            st.error(
                "音声認識ライブラリを読み込めません。requirements.txtを確認してください。"
            )
        else:
            recorded_audio = st.audio_input(
                "音声を録音",
                sample_rate=16000,
                key=f"voice_audio_{st.session_state['voice_audio_version']}",
            )

            if recorded_audio is not None:
                st.audio(recorded_audio)

                if st.button("録音内容を文字に変換"):
                    recognized_text = transcribe_recorded_audio(recorded_audio)
                    if recognized_text:
                        st.session_state["voice_transcript"] = recognized_text
                        st.success("音声を文字に変換しました。内容を確認して送信してください。")

            voice_message = st.text_area(
                "認識結果・連絡内容",
                key="voice_transcript",
                placeholder="録音を文字に変換すると、ここに認識結果が表示されます。",
                height=130,
            )

            voice_tags = detect_tags(voice_message)
            st.info(f"自動タグ：{', '.join(voice_tags) if voice_tags else '通常'}")

            if st.button("認識した連絡を送信・記録する", type="primary"):
                if recorded_audio is None:
                    st.warning("先に音声を録音してください。")
                elif not voice_message.strip():
                    st.warning("録音内容を文字に変換するか、連絡内容を入力してください。")
                elif len(target_ships) == 0:
                    st.warning("対象船を選んでください。")
                else:
                    sent_targets = target_ships.copy()
                    log_id = add_log(sender, voice_message.strip(), sent_targets)
                    st.session_state["send_notice"] = {
                        "log_id": log_id,
                        "targets": sent_targets,
                    }
                    reset_send_form()
                    st.rerun()


elif mode == "船側確認":
    st.header("船側確認")
    show_guide("<b>概要：</b>自船宛ての連絡を確認し、確認状況を登録します。")

    ship_name = st.selectbox("自分の船を選択", ships)
    show_ship_messages(ship_name)


elif mode == "確認状況":
    st.header("確認状況")
    show_guide("<b>概要：</b>連絡ごとに、各船の確認済み・未確認状況を確認します。")

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


elif mode == "システム設定":
    st.header("システム設定")

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


elif mode == "システム概要":
    st.header("システム概要")
    st.markdown("""
### システム名称
**漁業連絡管理システム**

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
