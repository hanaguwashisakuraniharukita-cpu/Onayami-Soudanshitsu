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
        "- **個人情報の保護**：お子様の実名、学校名、クラスなどは入力しないでください（実名等が含まれる場合は自動ブロックされます）。「小5」「長男」「Aさん（仮名）」など一般的な表現でご相談ください。\n"
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
# 4. セッション状態の初期化 ＆ 検知関数
# ==========================================
if "messages" not in st.session_state:
    st.session_state.messages = []

if "audit_logs" not in st.session_state:
    st.session_state.audit_logs = []

if "action_plan" not in st.session_state:
    st.session_state.action_plan = ""

# 高リスク（委任禁止領域）検知用キーワード
HIGH_RISK_KEYWORDS = [
    "死にたい", "消えたい", "自殺", "自傷", "リストカット", "虐待", "暴力",
    "うつ病", "発達障害", "ADHD", "ASD", "LD", "学習障害", "不登校", "いじめ",
    "診断", "投薬", "精神科", "心療内科", "パニック"
]

def check_high_risk(text: str) -> bool:
    return any(kw in text for kw in HIGH_RISK_KEYWORDS)

# 個人情報（子どもの実名・学校名・クラス名）検知フィルター
SAFE_HONORIFIC_WORDS = {
    "お子", "おこ", "お母", "お父", "お兄", "お姉", "弟", "妹",
    "おじい", "おばあ", "お嬢", "お坊", "赤", "皆", "みな", "たく", "沢",
    "奥", "旦那", "ご主人", "お医者", "看護師", "保育士", "先生", "櫻井", "AI",
    "A", "B", "C", "D", "〇", "◯"
}

def check_personal_info(text: str) -> tuple[bool, str]:
    """
    子どもの実名や学校名・クラス名が含まれているか判定する。
    戻り値: (検知されたか: bool, 検知理由メッセージ: str)
    """
    # 1. 学校名・クラス名のパターン（〇〇小学校、〇年〇組 など）
    school_pattern = r"[一-龥ぁ-んァ-ヶー]{2,}(?:小学校|中学校|高等学校|高校|学園|幼稚園|保育園)|[1-6１-６一二三四五六]年[1-9１-９一二三四五六七八九十A-Za-z]組"
    if re.search(school_pattern, text):
        return True, "具体的な学校名やクラス名が含まれている可能性があります。「小5」「中学生」などの表現に変えてご入力ください。"

    # 2. 名前の明示パターン（「名前は〇〇」「息子の〇〇」「長女の〇〇」など）
    intro_pattern = r"(?:名前は|本名は|(?:息子|娘|長男|次男|三男|長女|次女|三女|子ども|子供)の)\s*([一-龥ぁ-んァ-ヶ]{2,6})(?:です|といいます|と言います|が|は|を|に)"
    match_intro = re.search(intro_pattern, text)
    if match_intro:
        word = match_intro.group(1)
        # 一般名詞（「成績」「宿題」「性格」「こと」など）を除外
        exclude_nouns = {"成績", "宿題", "勉強", "テスト", "性格", "様子", "態度", "こと", "事", "話", "悩み", "友達", "友人", "先生", "進路", "部活", "習い事"}
        if word not in exclude_nouns:
            return True, f"お子様のお名前（「{word}」）が含まれている可能性があります。プライバシー保護のため、お名前は伏せて「息子」「娘」「小5の子ども」などの表現でご入力ください。"

    # 3. 敬称付きの名前パターン（〇〇くん、〇〇ちゃん、〇〇君、〇〇さん）
    honorific_pattern = r"([一-龥ぁ-んァ-ヶ]{1,5})(くん|ちゃん|君|さん)"
    for match in re.finditer(honorific_pattern, text):
        prefix = match.group(1)
        # 「お子さん」「お母さん」「お兄ちゃん」などの一般語は許可
        if prefix not in SAFE_HONORIFIC_WORDS and not prefix.endswith(("のお子", "のお母", "のお父", "の先生")):
            return True, f"個人名（「{match.group(0)}」）が含まれている可能性があります。プライバシー保護のため、実名は伏せてご入力ください（仮名の場合は「Aさん」等をご利用ください）。"

    return False, ""

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

2. 呼称の「さん」付け統一と、性別不明時の確認ルール（重要）：
   ・お子さんや登場人物を呼ぶ際は、性別にかかわらず「〜くん」「〜ちゃん」は絶対に使わず、全員 **「さん」付け**（基本は「お子さん」、イニシャル等の場合も「Aさん」）で統一してください。
   ・親御さんの発言からお子さんが男子か女子か判断がつきかねるとき（「息子」「娘」「男の子」「女の子」などの情報がまだないとき）は、初回の返答の中で **「確認ですが、お子さんは男の子でしょうか、女の子でしょうか？」** と優しく尋ねてください。

3. 実名・個人情報の徹底排除（システムフィルターをすり抜けた場合）：
   万が一、親御さんが呼び捨てなどで「お子様の実名」や「具体的な学校名」を入力された場合は、その名前を絶対に復唱せず、「プライバシー保護のため、お子様のお名前は伏せて『お子さん』や学年でお話しくださいね」と優しくお伝えして再入力を促してください。

4. 委任禁止領域（Never-Delegate）と専門窓口へのエスカレーション：
   医療・発達障害の診断、深刻なメンタルヘルス不調、自傷他害の恐れ、深刻ないじめや虐待など、AIが独断で判断を下すと重大なリスクがある相談については、決してAIだけで解決・診断しようとしないでください。
   親御さんのつらいお気持ちを温かく受け止めた上で、「こうした大切なお悩みは、私（AI）だけで判断せず、人間が丁寧にお伺いすることが大切です。ぜひ当相談室の専門窓口である **櫻井（k.sakurai@aiwa-learning.com）** まで直接ご連絡・ご相談ください」と明確にご案内してください。

5. 専門用語は「平易な解説・日常の比喩」と必ずセットで使う（1回につき1〜2個まで）：
   専門家としての説得力を保つため、適切な場面では専門用語（ワーキングメモリ、認知オーバーロード、想起練習、分散学習、インターリーブ、流暢性の錯覚、集中モードと拡散モード、レースカー脳とハイカー脳、手続き的記憶と宣言的記憶、ポモドーロ・テクニック、チャンク化、島皮質、BDNF、バリデーション、快楽適応、セイバリング、WOOPモデル、If-Thenプランなど）を使用して構いません。
   ただし、必ず直後に「小学生でもイメージできる日常の例えや平易な解説」を添えてください。知識のひけらかしにならないよう、1回の返答で使う専門用語は最大1〜2個に絞ってください。

6. 「指示（Telling）」ではなく「一緒に作戦を立てる（We Do）」姿勢で1つずつ質問する：
   最初から解決策を長々とまとめて出力しないでください。
   ・ステップ1（感情の受容）：まず親御さんの気持ち（「それは心配になりますよね」「毎日本当にお疲れ様です」など）を肯定・受容（バリデーション）し、親御さんにとっての『感情の避難所』になってください。
   ・ステップ2（1問1答での状況把握）：状況を把握するための質問を【1回の返答につき1つだけ】投げかけてください（性別が不明な場合は、性別の確認を含めて1つ質問してください。1回の返答は3〜6文程度）。
   ・ステップ3（共同作戦会議とIf-Thenプラン）：数回のやり取りで状況が見えてきたら、「〜してください」と一方的に命じるのではなく、「何がハードルになっていそうか（障害）」を一緒に考え、「もし［きっかけ］が起きたら、そのときは［小さな行動］をする（If-Thenプラン）」の形で、今日から無理なく試せる作戦を1つ一緒に作ってください。
   ※具体的な「もし〜なら、〜する」の作戦がまとまった時は、返答の最後に以下の形式で1行添えてください：
   【今日の作戦】もし〇〇なら、△△する

7. 関係のない話（雑談）への対応：
   子育てや学習と関係のない話題が出た場合は、冷たく遮らずに1〜2回ほど和やかに会話に付き合ってください。その後、「ところで、最近お子さんのご様子や、ご自身の体調はいかがですか？」など、自然にお悩み相談の話題へ戻してください。
"""

# 利用可能なモデル一覧（上限到達時は上から順に自動フォールバック）
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
        # Step 1: 個人情報（実名・学校名）フィルターによる事前ブロック判定
        has_pii, pii_warning_msg = check_personal_info(prompt)

        if has_pii:
            # APIには送信せず、画面上で警告を出して弾く
            st.warning(f"🛡️ **入力がブロックされました**：{pii_warning_msg}")
            # 監査ログには個人情報を伏せた状態でブロック実績のみ記録
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
            # Step 2: 個人情報がなければ通常処理へ進む
            is_high_risk = check_high_risk(prompt)

            st.session_state.messages.append({"role": "user", "content": prompt})
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

                if i == len(st.session_state.messages) - 1 and m["role"] == "user" and is_high_risk:
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
                                        yield chunk.text

                            full_response = st.write_stream(stream_generator())
                        else:
                            response = client.models.generate_content(
                                model=attempt_model,
                                contents=contents,
                            )
                            full_response = response.text
                            thinking_placeholder.markdown(full_response)

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
