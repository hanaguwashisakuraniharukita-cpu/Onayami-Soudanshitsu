import csv
import io
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from google import genai
from google.genai import errors
from google.genai import types

# ==========================================
# 1. 日本標準時（JST）へのタイムゾーン設定
# ==========================================
os.environ["TZ"] = "Asia/Tokyo"
if hasattr(time, "tzset"):
    time.tzset()

JST = ZoneInfo("Asia/Tokyo")

st.set_page_config(page_title="お悩み相談室", page_icon="💬", layout="centered")
st.title("💬 お悩み相談室")

# ==========================================
# 2. 事前ガードレール（個人情報保護・AIの境界明示）
# ==========================================
with st.container(border=True):
    st.markdown(
        "🔒 **安心してご相談いただくためのお願い**\n"
        "- **個人情報の保護**：お子様の実名（フルネームや下のお名前）、学校名、クラスなどは入力しないでください（検知された場合は自動ブロックされます）。「小5の母です」「長男が」など一般的な表現でご相談ください。\n"
        "- **この相談室の役割**：AIは家庭での工夫を一緒に探す「壁打ち相手（初期スクリーニング）」です。医療・心理的診断や緊急性の高いご相談については、人間の専門窓口（櫻井宛：`k.sakurai@aiwa-learning.com`）へおつなぎします。"
    )

# ==========================================
# 3. 3つのPDF知識データの読み込み（キャッシュ）
# ==========================================
PDF_FILES = [
    "happy_parenting_wellbeing_guide.pdf",
    "parent_guide_brain_science_learning.pdf",
    "Learning how to learn.pdf",
]

@st.cache_data
def load_all_pdfs(file_list):
    loaded = []
    for file_path in file_list:
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                loaded.append(f.read())
    return loaded

pdf_bytes_list = load_all_pdfs(PDF_FILES)

# 現在の日本日時と時間帯モードの取得
weekdays = ["月", "火", "水", "木", "金", "土", "日"]
now_jst = datetime.now(JST)
current_time_str = f"{now_jst.strftime('%Y年%m月%d日')}({weekdays[now_jst.weekday()]}) {now_jst.strftime('%H:%M')}"

hour = now_jst.hour
if 5 <= hour < 11:
    time_context = "現在は【朝〜午前】です。意志力（ウィルパワー）が満タンな時間帯なので、一番気が進まない課題（カエル）に短時間だけ取り組む工夫なども有効です。"
elif 11 <= hour < 17:
    time_context = "現在は【日中】です。行き詰まりがある場合は、散歩やお茶などで頭を休める『拡散モード』や、日常の小さな幸せを5分間味わう『セイバリング』も適しています。"
elif 17 <= hour < 22:
    time_context = "現在は【夕方〜夜】です。親御さんも子どもも1日の疲れが出てくる時間帯です。詰め込みよりも、今日取り組んだ過程（プロセス）の承認や、寝る前の2分間だけ今日学んだことを思い出す軽い振り返りを勧めてください。"
else:
    time_context = "現在は【夜遅い時間帯（22時以降〜深夜）】です。脳の作業机（ワーキングメモリ）も意志力も消耗しています。今夜は難しい反省会や詰め込みは避け、記憶の定着と脳のお掃除（老廃物除去）のためにしっかり睡眠（7〜9時間）をとることを最優先で労ってください。"

# ==========================================
# 4. セッション状態の初期化 ＆ 検知・変換関数
# ==========================================
if "messages" not in st.session_state:
    st.session_state.messages = []

if "audit_logs" not in st.session_state:
    st.session_state.audit_logs = []

if "action_plan" not in st.session_state:
    st.session_state.action_plan = ""

HIGH_RISK_KEYWORDS = [
    "死にたい", "消えたい", "自殺", "自傷", "リストカット", "虐待", "暴力",
    "うつ病", "発達障害", "ADHD", "ASD", "LD", "学習障害", "不登校", "いじめ",
    "診断", "投薬", "精神科", "心療内科", "パニック"
]

def check_high_risk(text: str) -> bool:
    return any(kw in text for kw in HIGH_RISK_KEYWORDS)

# 「〜の母」「〜ちゃん/くん」で除外する一般語リスト
SAFE_ROLE_WORDS = {
    "お子", "おこ", "お母", "お父", "お兄", "お姉", "弟", "妹", "姉", "兄",
    "おじい", "おばあ", "お嬢", "お坊", "赤", "皆", "みな", "たく", "沢",
    "奥", "旦那", "ご主人", "お医者", "看護師", "保育士", "先生", "櫻井", "AI",
    "A", "B", "C", "D", "〇", "◯",
    "小学生", "中学生", "高校生", "男の子", "女の子", "男子", "女子", "子供", "子ども", "子",
    "息子", "娘", "長男", "次男", "三男", "長女", "次女", "三女", "一人っ子", "双子", "末っ子",
    "小1", "小2", "小3", "小4", "小5", "小6", "小１", "小２", "小３", "小４", "小５", "小６",
    "中1", "中2", "中3", "中１", "中２", "中３", "高1", "高2", "高3", "高１", "高２", "高３",
    "1年生", "2年生", "3年生", "4年生", "5年生", "6年生",
    "１年生", "２年生", "３年生", "４年生", "５年生", "６年生",
    "一年生", "二年生", "三年生", "四年生", "五年生", "六年生",
    "受験生", "不登校", "反抗期", "思春期", "共働き", "シングル"
}

def check_personal_info(text: str) -> tuple[bool, str]:
    """
    確実に個人情報と判別できるパターン（学校名、クラス名、明示的な名乗り、くん/ちゃん付け）を事前ブロックする。
    ※「子どもの勉強時間が」のような一般名詞の所有格は誤爆を防ぐためここでは弾かず、AIの文脈判定に委ねる。
    """
    # 1. 学校名・クラス名のパターン（〇〇小学校、〇年〇組 など）
    school_pattern = r"[一-龥ぁ-んァ-ヶー]{2,}(?:小学校|中学校|高等学校|高校|学園|幼稚園|保育園)|[1-6１-６一二三四五六]年[1-9１-９一二三四五六七八九十A-Za-z]組"
    if re.search(school_pattern, text):
        return True, "具体的な学校名やクラス名が含まれている可能性があります。「小5」「中学生」などの表現に変えてご入力ください。"

    # 2. 明示的な名前紹介パターン（「名前は〇〇」「〇〇という名前」）
    explicit_name_pattern = r"(?:名前は|本名は|氏名は)\s*([一-龥ぁ-んァ-ヶ]{2,8}?)(?:です|といいます|と言います|と申します|といい|、|。|$)"
    match_exp = re.search(explicit_name_pattern, text)
    if match_exp:
        return True, f"お名前（「{match_exp.group(1)}」）が含まれている可能性があります。プライバシー保護のため、お名前は伏せてご入力ください。"

    # 3. 「〇〇の母/父/親です」パターン（例：「小5の小川環の母です」→「小川環」を検知）
    parent_of_pattern = r"(?:の|^|\s|、|。)([一-龥ぁ-んァ-ヶ]{2,8})の(?:母|父|親|保護者|ママ|パパ|母親|父親)"
    for match in re.finditer(parent_of_pattern, text):
        candidate = match.group(1)
        if candidate not in SAFE_ROLE_WORDS and not candidate.endswith(("の子", "の子供", "の子ども", "の息子", "の娘", "の生徒", "の児童")):
            return True, f"お子様のお名前（「{candidate}」）が含まれている可能性があります。プライバシー保護のため、実名は伏せて「小5の母です」「長男の母です」のようにご入力ください。"

    # 4. 敬称付きの名前パターン（〇〇くん、〇〇ちゃん、〇〇君）
    honorific_pattern = r"([一-龥ぁ-んァ-ヶ]{1,6})(くん|ちゃん|君)"
    for match in re.finditer(honorific_pattern, text):
        prefix = match.group(1)
        if prefix not in SAFE_ROLE_WORDS and not prefix.endswith(("のお子", "のお兄", "のお姉", "の弟", "の妹", "の赤")):
            return True, f"個人名（「{match.group(0)}」）が含まれている可能性があります。プライバシー保護のため、実名は伏せてご入力ください。"

    return False, ""

def enforce_san_honorific(text: str) -> str:
    """
    AIの出力テキスト内に「〜くん」「〜ちゃん」「〜君」が含まれていた場合、
    プログラム側で強制的に「〜さん」へ置換する（「ちゃんと」「たくさん」等の一般語は保護）。
    """
    protected = text.replace("ちゃんと", "__CHANTO__").replace("たくさん", "__TAKUSAN__")
    protected = re.sub(r"([一-龥ぁ-んァ-ヶA-Za-z〇◯]+?)(?:くん|ちゃん|君)", r"\1さん", protected)
    return protected.replace("__CHANTO__", "ちゃんと").replace("__TAKUSAN__", "たくさん")

# ==========================================
# 5. AIの対話・ガバナンスガイドライン
# ==========================================
COUNSELOR_GUIDELINES = f"""
現在の日本時間: {current_time_str}
時間帯の配慮指針: {time_context}

あなたは、教育心理学・脳科学・幸福学の深い知見を持ち、子育てや家庭学習に悩む親御さんに温かく寄り添う経験豊富な専門家カウンセラーです。
一緒に渡された3つの知識データの内容をすべて「あなた自身の専門知識・経験」として完全に内面化し、以下のルールを厳守して対話してください。

【絶対守るべき対話・ガバナンスルール】
1. 資料の存在を完全に隠す：
   「資料によると」「ガイドラインでは」「PDFには」「添付データでは」といった表現は絶対に使わないでください。すべてあなた自身の知見として自然に語ってください。

2. 【最重要】全員「さん」付けで統一（「くん」「ちゃん」は絶対禁止）＆ 性別確認ルール：
   ・お子さんが男の子であっても女の子であっても、「〜くん」「〜ちゃん」「〜君」という呼称は**絶対に1度たりとも使わないでください**。
   ・お子さんを呼ぶときは常に **「お子さん」**（または仮名の場合は「〇〇さん」）と **「さん」付け** で統一してください。
   ・親御さんの発言からお子さんが男子か女子か判断がつきかねるとき（「息子」「娘」「男の子」「女の子」などの情報がまだないとき）は、初回の返答の中で **「確認ですが、お子さんは男の子でしょうか、女の子でしょうか？」** と尋ねてください。その際、親御さんから「男の子です」と返答があった後も、絶対に「くん」には変えず、引き続き「お子さん」（さん付け）で通してください。

3. 【最重要】実名（人名）・学校名の文脈ブロック：
   もし親御さんの入力文の中に、明確な「人物の実名（苗字・下の名前・フルネーム、例：『小川環』『太郎』『花子』など）」や「具体的な学校名・塾名」が含まれていると文脈から判断した場合は、相談への回答を一切行わず、必ず文頭に **`【個人情報ブロック】`** という文字列を出力し、「プライバシー保護のため、お子様の実名は伏せて『お子さん』『息子』『小5の子ども』のようにご入力くださいね」とだけ案内してください。
   （※「勉強時間」「集中力」「宿題」などの一般名詞や、「Aさん」などのアルファベット仮名は実名ではないため絶対にブロックしないでください）

4. 委任禁止領域（Never-Delegate）と専門窓口へのエスカレーション：
   医療・発達障害の診断、深刻なメンタルヘルス不調、自傷他害の恐れ、深刻ないじめや虐待など、AIが独断で判断を下すと重大なリスクがある相談については、決してAIだけで解決・診断しようとしないでください。
   親御さんのつらいお気持ちを温かく受け止めた上で、「こうした大切なお悩みは、私（AI）だけで判断せず、人間が丁寧にお伺いすることが大切です。ぜひ当相談室の専門窓口である **櫻井（k.sakurai@aiwa-learning.com）** まで直接ご連絡・ご相談ください」と明確にご案内してください。

5. 専門用語は「平易な解説・日常の比喩」と必ずセットで使う（1回につき1〜2個まで）：
   適切な場面では専門用語（ワーキングメモリ、認知オーバーロード、想起練習、分散学習、インターリーブ、流暢性の錯覚、集中モードと拡散モード、レースカー脳とハイカー脳、手続き的記憶と宣言的記憶、ポモドーロ・テクニック、チャンク化、島皮質、BDNF、バリデーション、快楽適応、セイバリング、WOOPモデル、If-Thenプランなど）を使用して構いませんが、必ず直後に「小学生でもイメージできる日常の例えや平易な解説」を添えてください。

6. 「指示（Telling）」ではなく「一緒に作戦を立てる（We Do）」姿勢で1つずつ質問する：
   最初から解決策を長々とまとめて出力しないでください。
   ・ステップ1（感情の受容）：まず親御さんの気持ち（「それは心配になりますよね」「毎日本当にお疲れ様です」など）を肯定・受容（バリデーション）してください。
   ・ステップ2（1問1答での状況把握）：状況を把握するための質問を【1回の返答につき1つだけ】投げかけてください（性別が不明な場合は性別の確認を行い、1回の返答は3〜6文程度に抑えてください）。
   ・ステップ3（共同作戦会議とIf-Thenプラン）：数回のやり取りで状況が見えてきたら、「何がハードルになっていそうか（障害）」を一緒に考え、「もし［きっかけ］が起きたら、そのときは［小さな行動］をする（If-Thenプラン）」の形で、今日から無理なく試せる作戦を1つ一緒に作ってください。
   ※具体的な「もし〜なら、〜する」の作戦がまとまった時は、返答の最後に以下の形式で1行添えてください：
   【今日の作戦】もし〇〇なら、△△する

7. 関係のない話（雑談）への対応：
   子育てや学習と関係のない話題が出た場合は、1〜2回ほど和やかに会話に付き合った後、自然にお悩み相談の話題へ戻してください。
"""

# 毎ターンの末尾に付与する厳守リマインダー
TURN_REMINDER = """
【システム最優先ルール（厳守）】
・お子さんが男の子であっても「〜くん」「〜ちゃん」「〜君」は絶対に使用禁止です。必ず「お子さん」または「〜さん」と表現してください。
・もし今回のユーザー発言に具体的な人物の実名（例：小川環、太郎など）が含まれている場合のみ、相談に答えず文頭に必ず `【個人情報ブロック】` と出力してください（一般名詞はブロックしないこと）。
"""

AVAILABLE_MODELS = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.1-pro"]

# ==========================================
# 6. サイドバー（保護者向けメニュー ＆ 折りたたみ管理者メニュー）
# ==========================================
with st.sidebar:
    st.subheader("📝 今日の作戦メモ")
    if st.session_state.action_plan:
        st.success(st.session_state.action_plan)
    else:
        st.caption("対話を通じて「もし〜なら、〜する」という具体的な作戦が決まると、ここに自動記録されます。")

    if st.button("🗑️ 会話履歴をクリアする", use_container_width=True):
        st.session_state.messages = []
        st.session_state.action_plan = ""
        st.rerun()

    st.divider()
    st.markdown(
        "📩 **個別・専門相談窓口**\n"
        "AIでは判断が難しいご相談や、直接のサポートをご希望の場合は以下へご連絡ください。\n\n"
        "**担当：櫻井**\n"
        "[k.sakurai@aiwa-learning.com](mailto:k.sakurai@aiwa-learning.com)"
    )

    st.divider()

    with st.expander("🔧 管理者・ガバナンス設定"):
        selected_model = st.selectbox(
            "優先モデル選択（上限時は自動切替）",
            AVAILABLE_MODELS,
            index=0,
        )
        use_streaming = st.checkbox("ストリーミング表示を有効にする", value=True)

        default_key = st.secrets.get("GEMINI_API_KEY") if "GEMINI_API_KEY" in st.secrets else ""
        input_api_key = st.text_input("Gemini API Key (未設定時用)", value="", type="password")
        api_key = default_key if default_key else input_api_key

        st.markdown("---")
        st.markdown("📊 **運用テレメトリ（分母除外なし）**")
        total_logs = len(st.session_state.audit_logs)
        flagged_logs = sum(
            1 for log in st.session_state.audit_logs
            if log["status"] != "OK" or log["risk_escalated"] == "Yes" or log["feedback"] == "👎"
        )
        positive_logs = sum(1 for log in st.session_state.audit_logs if log["feedback"] == "👍")

        col1, col2 = st.columns(2)
        col1.metric("総応答数(分母)", f"{total_logs}件")
        col2.metric("要確認・滞留", f"{flagged_logs}件")
        st.caption(f"高評価(👍): {positive_logs}件 / ブロック・エラーもすべて分母に含めて集計")

        if st.session_state.audit_logs:
            output = io.StringIO()
            output.write("\ufeff")
            writer = csv.DictWriter(
                output,
                fieldnames=[
                    "turn_id", "timestamp_jst", "model", "status",
                    "risk_escalated", "feedback", "action_plan_extracted",
                    "user_prompt_preview", "assistant_response_preview"
                ],
            )
            writer.writeheader()
            writer.writerows(st.session_state.audit_logs)

            st.download_button(
                label="📥 監査ログをCSVダウンロード",
                data=output.getvalue(),
                file_name=f"audit_log_{now_jst.strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

# ==========================================
# 7. チャット描画 ＆ フィードバック記録処理
# ==========================================
if not api_key:
    st.info("現在準備中です。管理者の方は左メニューの「🔧 管理者・ガバナンス設定」または Secrets に API キーを設定してください。", icon="🗝️")
else:
    client = genai.Client(api_key=api_key.strip())

    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant" and "log_index" in message:
                log_idx = message["log_index"]
                if log_idx < len(st.session_state.audit_logs):
                    current_fb = st.session_state.audit_logs[log_idx]["feedback"]
                    fb_col1, fb_col2, fb_col3 = st.columns([1, 1, 8])
                    if fb_col1.button("👍", key=f"up_{idx}", help="役に立った"):
                        st.session_state.audit_logs[log_idx]["feedback"] = "👍"
                        st.rerun()
                    if fb_col2.button("👎", key=f"down_{idx}", help="改善が必要（監査対象として記録）"):
                        st.session_state.audit_logs[log_idx]["feedback"] = "👎"
                        st.rerun()
                    if current_fb != "未評価":
                        fb_col3.caption(f"評価記録済: {current_fb}")

    # ==========================================
    # 8. ユーザー入力・個人情報ブロック・Gemini API呼び出し
    # ==========================================
    if prompt := st.chat_input("今日はどのようなご相談ですか（お子様の実名等は伏せてご入力ください）"):
        # Step 1: Python正規表現による事前ブロック判定（確実なパターンのみ）
        has_pii, pii_warning_msg = check_personal_info(prompt)

        if has_pii:
            st.warning(f"🛡️ **入力がブロックされました**：{pii_warning_msg}")
            log_index = len(st.session_state.audit_logs)
            st.session_state.audit_logs.append(
                {
                    "turn_id": log_index + 1,
                    "timestamp_jst": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
                    "model": "Blocked_Before_API",
                    "status": "Blocked_PII",
                    "risk_escalated": "No",
                    "feedback": "未評価",
                    "action_plan_extracted": "",
                    "user_prompt_preview": "(個人情報検知のため非表示・送信ブロック済)",
                    "assistant_response_preview": pii_warning_msg,
                }
            )
        else:
            # Step 2: 事前フィルターを通過した場合
            is_high_risk = check_high_risk(prompt)

            st.session_state.messages.append({"role": "user", "content": prompt})
            user_msg_placeholder = st.empty()
            with user_msg_placeholder.container():
                with st.chat_message("user"):
                    st.markdown(prompt)

            contents = []
            for i, m in enumerate(st.session_state.messages):
                parts = []
                if i == 0 and m["role"] == "user":
                    for pdf_data in pdf_bytes_list:
                        parts.append(
                            types.Part.from_bytes(
                                data=pdf_data,
                                mime_type="application/pdf",
                            )
                        )
                    parts.append(types.Part.from_text(text=COUNSELOR_GUIDELINES))

                if i == len(st.session_state.messages) - 1 and m["role"] == "user":
                    parts.append(types.Part.from_text(text=TURN_REMINDER))
                    if is_high_risk:
                        parts.append(
                            types.Part.from_text(
                                text="【システム注記：相談内容に専門的判断や慎重な配慮を要するキーワードが含まれています。AI独自の診断や断定は避け、共感を示しつつ必ず専門窓口 櫻井（k.sakurai@aiwa-learning.com）への相談を案内してください】"
                            )
                        )

                parts.append(types.Part.from_text(text=m["content"]))

                contents.append(
                    types.Content(
                        role="model" if m["role"] == "assistant" else "user",
                        parts=parts,
                    )
                )

            fallback_models = [selected_model] + [m for m in AVAILABLE_MODELS if m != selected_model]

            full_response = ""
            success = False
            error_status = "OK"
            used_model = selected_model

            assistant_msg_placeholder = st.empty()
            with assistant_msg_placeholder.container():
                with st.chat_message("assistant"):
                    thinking_placeholder = st.empty()
                    thinking_placeholder.markdown("（・・・今考えています）")

                    for attempt_model in fallback_models:
                        used_model = attempt_model
                        try:
                            if use_streaming:
                                response_stream = client.models.generate_content_stream(
                                    model=attempt_model,
                                    contents=contents,
                                )

                                def stream_generator():
                                    for chunk in response_stream:
                                        if chunk.text:
                                            thinking_placeholder.empty()
                                            yield enforce_san_honorific(chunk.text)

                                full_response = st.write_stream(stream_generator())
                            else:
                                response = client.models.generate_content(
                                    model=attempt_model,
                                    contents=contents,
                                )
                                full_response = enforce_san_honorific(response.text)
                                thinking_placeholder.markdown(full_response)

                            full_response = enforce_san_honorific(full_response)
                            success = True
                            error_status = "OK"
                            break

                        except errors.APIError as e:
                            if e.code in [429, 503] and attempt_model != fallback_models[-1]:
                                continue
                            thinking_placeholder.empty()
                            error_status = f"APIError_{e.code}"
                            if e.code == 429:
                                st.error("現在すべてのモデルで無料枠の利用上限に達しています。しばらく時間を置くか、APIキーのプラン設定をご確認ください。")
                            else:
                                st.error(f"**Gemini API Error [{e.code}]**: {e.message}")
                            break
                        except Exception as e:
                            thinking_placeholder.empty()
                            error_status = f"Error_{type(e).__name__}"
                            st.error(f"**Error**: {type(e).__name__} - {str(e)}")
                            break

            # Step 3: AI側が文脈から実名を検知して【個人情報ブロック】を発動した場合
            if "【個人情報ブロック】" in full_response:
                user_msg_placeholder.empty()
                assistant_msg_placeholder.empty()
                st.session_state.messages.pop()

                clean_warn = full_response.replace("【個人情報ブロック】", "").strip()
                if not clean_warn:
                    clean_warn = "お子様のお名前（実名）が含まれている可能性があります。プライバシー保護のため、お名前は伏せてご入力ください。"
                st.warning(f"🛡️ **入力がブロックされました**：{clean_warn}")

                log_index = len(st.session_state.audit_logs)
                st.session_state.audit_logs.append(
                    {
                        "turn_id": log_index + 1,
                        "timestamp_jst": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
                        "model": used_model,
                        "status": "Blocked_PII_by_AI",
                        "risk_escalated": "No",
                        "feedback": "未評価",
                        "action_plan_extracted": "",
                        "user_prompt_preview": "(個人情報検知のため非表示・ブロック済)",
                        "assistant_response_preview": clean_warn,
                    }
                )
            else:
                extracted_plan = ""
                if full_response:
                    match = re.search(r"【今日の作戦】(.+)", full_response)
                    if match:
                        extracted_plan = match.group(1).strip()
                        st.session_state.action_plan = extracted_plan

                escalated = is_high_risk or ("k.sakurai@aiwa-learning.com" in full_response)

                log_index = len(st.session_state.audit_logs)
                st.session_state.audit_logs.append(
                    {
                        "turn_id": log_index + 1,
                        "timestamp_jst": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
                        "model": used_model,
                        "status": error_status,
                        "risk_escalated": "Yes" if escalated else "No",
                        "feedback": "未評価",
                        "action_plan_extracted": extracted_plan,
                        "user_prompt_preview": prompt[:60],
                        "assistant_response_preview": full_response[:60] if full_response else "(応答失敗・未解決)",
                    }
                )

                if success and full_response:
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": full_response,
                            "log_index": log_index,
                        }
                    )
                    st.rerun()
                else:
                    st.session_state.messages.pop()
