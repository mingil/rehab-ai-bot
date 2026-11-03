import os
import time
import logging
from google import genai
from google.genai import types

logger = logging.getLogger("JCBot")

FAILURE_PREFIX = "⚠️ AI 분석을 불러오지 못했습니다"


class PaperAnalyzer:
    def __init__(self):
        raw_key = os.environ.get("GEMINI_API_KEY", "")
        api_key = str(raw_key).strip().strip('"').strip("'").strip()
        if not api_key or api_key.startswith("your_"):
            raise ValueError("❌ GEMINI_API_KEY가 없거나 유효하지 않습니다.")

        self.client = genai.Client(api_key=api_key)

        # 🚀 3-Tier 하이브리드 모델 폴백 체인 (환경변수 GEMINI_MODEL 커스텀 지원)
        primary_model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip().strip('"').strip("'")
        if not primary_model:
            primary_model = "gemini-3.8-flash"
        self.model_name = primary_model

        default_fallbacks = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]
        self.model_candidates = [primary_model] + [m for m in default_fallbacks if m != primary_model]

    @staticmethod
    def is_valid_analysis(text):
        return bool(text and str(text).strip() and not str(text).strip().startswith(FAILURE_PREFIX))

    def _format_authors_for_prompt(self, raw_authors):
        if not raw_authors:
            return "저자 소속 정보 없음"

        author_lines = []
        for author in raw_authors:
            if isinstance(author, str):
                author_lines.append(f"- {author}")
            elif isinstance(author, dict):
                last = str(author.get('LastName', ''))
                first = str(author.get('ForeName', author.get('Initials', '')))
                affil_list = [info.get('Affiliation', '') for info in author.get('AffiliationInfo', []) if isinstance(info, dict)]
                affil = " | ".join(affil_list) if affil_list else "N/A"
                author_lines.append(f"- {last} {first}: {affil}")

        return "\n".join(author_lines[:5]) + ("\n... (이하 생략)" if len(raw_authors) > 5 else "")

    def analyze(self, paper, max_retries=3):
        authors_info = self._format_authors_for_prompt(paper.get('raw_authors', []))

        # 🎯 [최적화] EBM 기반 임상 전문의(Clinician) 특화 페르소나
        system_instruction = (
            "당신은 Evidence-Based Medicine(EBM)과 의료 인공지능(Digital Healthcare)에 정통한 대한민국 최고 수준의 재활의학과 전문의이자 의과대학 교수입니다. "
            "주어진 논문은 재활의학 분야에 인공지능(AI), 머신러닝, 딥러닝을 적용한 최신 연구입니다. "
            "엔지니어링 관점의 칭찬(단순히 정확도가 높다 등)은 배제하고, 철저히 '실제 재활 치료실/진료실 도입 가능성'과 '의료진 워크플로우 개선 여부'라는 냉철하고 실용적인 잣대로 팩트체크를 진행하십시오. "
            "바쁜 의사들이 한눈에 읽을 수 있도록 미사여구를 배제하고 직설적인 개조식(Bullet points)으로만 답변하십시오."
        )

        # 🎯 [최적화] 모바일 가독성을 극대화한 구조화된 출력 양식 강제
        prompt = f"""
아래 논문 메타데이터와 초록을 비판적으로 분석하여, 주어진 [출력 양식]에 완벽히 맞춰 브리핑을 작성하십시오.

[논문 정보]
- Title: {paper.get('title', 'N/A')}
- Journal: {paper.get('journal', 'N/A')}
- Authors:
{authors_info}

[Abstract]
{paper.get('abstract', 'N/A')}

[출력 양식] - 각 항목의 제목과 이모지를 그대로 유지하세요.

🎯 **시니어 교수의 한 줄 평**
(이 연구가 재활의학 임상에 던지는 화두나 한계를 단 한 문장으로 직관적이고 강력하게 요약)

🤖 **기술 및 데이터 스펙**
- **적용 기술:** (사용된 AI 모델/알고리즘 명시)
- **데이터 소스:** (환자 N수, 다기관/단일기관 여부, 영상/생체신호/EMR 등 데이터 종류)
- **핵심 성능:** (논문이 주장하는 정확도, AUC, 민감도/특이도 등 주요 지표)

🧐 **임상적 가치와 치명적 한계**
- **강점(Innovation):** (기존 재활 치료/진단 방식 대비 현실적으로 나아진 점)
- **한계(Red Flag):** (외부 검증(External Validation) 부재, 소규모/특정군 데이터에 의한 과적합 의심, Black-box 문제 등 팩트 폭격)

🏥 **실제 재활의학과 적용 시나리오**
(이 모델을 당장 병원 재활의학과에 도입한다면, [1] 어떤 과정(진단, 처방, 예후예측 등)에 쓰일 수 있고 [2] 현실적 장애물(수가, 규제, 순응도 등)은 무엇일지 평가하여 '적극 도입 / 관망 / 반려' 중 하나의 의견으로 제시)
"""

        safety_settings = [
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH)
        ]

        for model_name in self.model_candidates:
            for attempt in range(max_retries):
                try:
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            temperature=0.2,  # 일관된 팩트 폭격을 위해 낮은 온도 유지
                            safety_settings=safety_settings
                        )
                    )

                    if not response.text:
                        raise ValueError("응답 텍스트 비어있음")

                    return response.text.strip()

                except Exception as e:
                    logger.warning(f"⚠️ Gemini API 지연 [{model_name}] (시도 {attempt+1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep((2 ** attempt) * 4)
                    else:
                        logger.warning(f"⚠️ [{model_name}] 모델 응답 실패. 다음 백업 모델로 자동 전환을 시도합니다.")

        return f"{FAILURE_PREFIX}. (API 서버 응답 초과)"
