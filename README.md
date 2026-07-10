# 漁業連絡確認システム

## 概要
漁協側と船側が同じURLにアクセスし、連絡内容と確認状況を共有できるプロトタイプです。

## できること
- 漁協側が連絡を送信
- 手入力またはマイク音声認識で記録
- 重要ワードを自動タグ付け
- 船側が自分宛ての連絡を確認
- 「確認しました」ボタンで既読化
- 漁協側で船ごとの確認済み・未確認を確認
- SQLiteでデータ保存

## デモの流れ
1. 「漁協側：連絡を送る」で連絡を送信
2. 「船側：連絡を確認する」で船を選び、「確認しました」を押す
3. 「漁協側：確認状況を見る」で確認済み・未確認を確認

## 実行方法

```bash
pip install -r requirements.txt
streamlit run app.py
```

ブラウザで以下を開きます。

```text
http://localhost:8501
```

## 同じWi-Fiの他PC・スマホから見る方法

起動したPCで、IPアドレスを確認します。

Windowsの場合：

```bash
ipconfig
```

IPv4アドレスを確認します。例：

```text
192.168.1.10
```

その後、他のPCやスマホのブラウザで以下のように入力します。

```text
http://192.168.1.10:8501
```

うまくつながらない場合は、Streamlitを以下で起動してください。

```bash
streamlit run app.py --server.address 0.0.0.0
```

Windows Defender ファイアウォールで Python または Streamlit の通信を許可してください。

## GitHubで共有するとき

リポジトリには以下を入れます。

```text
app.py
requirements.txt
README.md
.gitignore
```

以下は自動生成されるのでGitHubに入れません。

```text
gyogyo_musen.db
__pycache__/
.venv/
```

## PyAudioでエラーが出る場合

```bash
pip install pipwin
pipwin install pyaudio
```

難しい場合は、手入力だけでもデモできます。


## CSSについて

画面デザインは `style.css` にまとめています。

```text
style.css
```

色や背景、カードの見た目を変えたい場合は、主に `style.css` を編集してください。
`app.py` のPython処理はなるべく触らず、デザインだけを変更できます。
