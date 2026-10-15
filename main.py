
# ============================================
# 동네별 인구 피라미드
# 지표 카드 3개 + 인구 비교 설명 + 고령화 주의 표시
# ============================================

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# --------------------------------------------
# 1. 기본 페이지 설정
# --------------------------------------------
st.set_page_config(
    page_title="동네별 인구 피라미드",
    page_icon="🏘️",
    layout="wide",
)


# --------------------------------------------
# 2. 따뜻한 크림색과 노란색으로 화면 꾸미기
# --------------------------------------------
st.markdown(
    """
    <style>
    .stApp {
        background-color: #FFF9ED;
        color: #4E3D2D;
    }

    [data-testid="stHeader"] {
        background-color: rgba(255, 249, 237, 0.95);
    }

    .block-container {
        max-width: 1400px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }

    h1, h2, h3 {
        color: #754D32;
    }

    [data-testid="stMetric"] {
        background-color: #FFF0CE;
        border: 1px solid #F0D8A7;
        border-radius: 14px;
        padding: 16px;
    }

    div[data-baseweb="select"] > div {
        background-color: #FFFEF8;
        border-radius: 10px;
        border-color: #E8D4B2;
    }

    .stAlert {
        border-radius: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------
# 3. 데이터 주소와 나이별 열 이름 준비
# --------------------------------------------
DATA_URL = (
    "https://raw.githubusercontent.com/"
    "first2022-cyber/contents/main/"
    "population_ts_yearly_gender.zip"
)

# 0세부터 99세까지, 그리고 100세 이상까지 총 101개 연령
age_labels = [f"{age}세" for age in range(100)] + ["100세 이상"]

# 데이터의 열 이름 예시: 남_0세, 여_0세, 남_100세 이상
male_columns = [f"남_{age}" for age in age_labels]
female_columns = [f"여_{age}" for age in age_labels]
age_columns = male_columns + female_columns


# --------------------------------------------
# 4. ZIP 압축 CSV 데이터 불러오기
# --------------------------------------------
@st.cache_data(ttl=3600)
def load_population_data():
    # UTF-8로 먼저 읽고, 인코딩 오류가 나면 CP949로 다시 시도합니다.
    try:
        data = pd.read_csv(
            DATA_URL,
            compression="zip",
            encoding="utf-8-sig",
        )
    except UnicodeDecodeError:
        data = pd.read_csv(
            DATA_URL,
            compression="zip",
            encoding="cp949",
        )

    # 열 이름 앞뒤의 공백 및 BOM 문자를 정리합니다.
    data.columns = [
        str(column).replace("\ufeff", "").strip()
        for column in data.columns
    ]

    return data


# --------------------------------------------
# 5. 앱 제목과 설명
# --------------------------------------------
st.title("🏘️ 동네별 인구 피라미드")

st.markdown(
    """
    우리 동네에는 연령별로 얼마나 많은 사람이 살고 있을까요?

    **시도 → 시군구 → 동** 순서로 지역을 선택하면
    남성과 여성의 나이별 인구, 평균연령, 고령화율을 확인할 수 있습니다.
    """
)

st.divider()


# --------------------------------------------
# 6. 데이터 불러오기
# --------------------------------------------
try:
    with st.spinner("인구 데이터를 불러오는 중입니다..."):
        df = load_population_data()

except Exception as error:
    st.error(
        "인구 데이터를 불러오지 못했습니다. "
        "인터넷 연결과 데이터 주소를 확인해 주세요."
    )
    st.caption(f"오류 내용: {error}")
    st.stop()


# --------------------------------------------
# 7. 필요한 열이 있는지 확인
# --------------------------------------------
location_columns = ["연도", "시도", "시군구", "동"]

missing_location_columns = [
    column
    for column in location_columns
    if column not in df.columns
]

missing_age_columns = [
    column
    for column in age_columns
    if column not in df.columns
]

if missing_location_columns:
    st.error(
        "데이터에 필요한 지역 열이 없습니다: "
        + ", ".join(missing_location_columns)
    )
    st.stop()

if missing_age_columns:
    st.error(
        "데이터에 필요한 나이별 인구 열이 없습니다. "
        "CSV의 열 이름을 확인해 주세요."
    )
    st.caption(
        "확인하지 못한 열 예시: "
        + ", ".join(missing_age_columns[:10])
    )
    st.stop()


# --------------------------------------------
# 8. 데이터에 들어 있는 최신 연도만 사용
# --------------------------------------------
# '2026년' 또는 '2026' 형태에서 연도 숫자를 추출합니다.
df["_연도_숫자"] = pd.to_numeric(
    df["연도"]
    .astype(str)
    .str.extract(r"(\d{4})", expand=False),
    errors="coerce",
)

if df["_연도_숫자"].notna().sum() == 0:
    st.error("데이터에서 연도를 찾지 못했습니다.")
    st.stop()

# 실제 데이터에 포함된 가장 최신 연도를 자동으로 선택합니다.
latest_year = int(df["_연도_숫자"].max())

latest_df = df.loc[
    df["_연도_숫자"] == latest_year
].copy()


# --------------------------------------------
# 9. 지역명과 인구값 정리
# --------------------------------------------
for column in ["시도", "시군구", "동"]:
    latest_df[column] = (
        latest_df[column]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "해당 없음")
    )

# 인구 열을 숫자로 변환합니다. 쉼표가 있는 숫자도 처리합니다.
for column in age_columns:
    latest_df[column] = pd.to_numeric(
        latest_df[column]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip(),
        errors="coerce",
    ).fillna(0)


# --------------------------------------------
# 10. 드롭다운의 선택값이 유효한지 확인
# --------------------------------------------
def set_valid_selection(key, options):
    # 선택할 지역이 없으면 안내를 표시합니다.
    if not options:
        st.error("선택할 지역 데이터가 없습니다.")
        st.stop()

    # 기존 선택값이 목록에 없다면 첫 번째 항목을 선택합니다.
    if (
        key not in st.session_state
        or st.session_state[key] not in options
    ):
        st.session_state[key] = options[0]


# --------------------------------------------
# 11. 시도 → 시군구 → 동 순서로 지역 선택
# --------------------------------------------
st.subheader("📍 지역 선택")

# 첫 번째 드롭다운: 시도
sido_options = sorted(latest_df["시도"].unique().tolist())

set_valid_selection("sido_select", sido_options)

selected_sido = st.selectbox(
    "① 시도",
    options=sido_options,
    key="sido_select",
)

# 선택한 시도에 속한 시군구만 표시합니다.
sido_df = latest_df.loc[
    latest_df["시도"] == selected_sido
]

sigungu_options = sorted(
    sido_df["시군구"].unique().tolist()
)

# 두 번째 드롭다운: 시군구
set_valid_selection("sigungu_select", sigungu_options)

selected_sigungu = st.selectbox(
    "② 시군구",
    options=sigungu_options,
    key="sigungu_select",
)

# 선택한 시도와 시군구에 속한 동만 표시합니다.
sigungu_df = sido_df.loc[
    sido_df["시군구"] == selected_sigungu
]

dong_options = sorted(
    sigungu_df["동"].unique().tolist()
)

# 세 번째 드롭다운: 동
set_valid_selection("dong_select", dong_options)

selected_dong = st.selectbox(
    "③ 동",
    options=dong_options,
    key="dong_select",
)

st.caption(f"📅 데이터 기준 연도: {latest_year}년")
st.divider()


# --------------------------------------------
# 12. 선택한 동네의 인구 데이터 찾기
# --------------------------------------------
selected_rows = latest_df.loc[
    (latest_df["시도"] == selected_sido)
    & (latest_df["시군구"] == selected_sigungu)
    & (latest_df["동"] == selected_dong)
]

if selected_rows.empty:
    st.warning("선택한 지역의 인구 데이터가 없습니다.")
    st.stop()

# 같은 지역의 행이 여러 개라면 나이별 인구를 합산합니다.
if len(selected_rows) == 1:
    population_by_age = selected_rows.iloc[0][age_columns]
else:
    population_by_age = selected_rows[age_columns].sum(axis=0)


# --------------------------------------------
# 13. 남성·여성 인구와 추가 지표 계산
# --------------------------------------------
male_values = [
    int(round(population_by_age[column]))
    for column in male_columns
]

female_values = [
    int(round(population_by_age[column]))
    for column in female_columns
]

# 같은 나이의 남성과 여성 인구를 더합니다.
# 위치 0은 0세, 위치 100은 100세 이상입니다.
population_by_age_total = [
    male_values[index] + female_values[index]
    for index in range(len(age_labels))
]

# 전체 남성·여성 인구
total_male = sum(male_values)
total_female = sum(female_values)
total_population = total_male + total_female


# --------------------------------------------
# 평균연령 계산
# --------------------------------------------
# 나이별 인구에 해당 나이를 곱한 뒤 모두 더하고
# 전체 인구수로 나눕니다.
#
# '100세 이상'은 계산을 위해 100세로 가정합니다.
# 따라서 평균연령은 추정값입니다.
if total_population > 0:
    average_age = (
        sum(
            age * population
            for age, population in enumerate(population_by_age_total)
        )
        / total_population
    )
else:
    average_age = None


# --------------------------------------------
# 고령화율 계산
# --------------------------------------------
# 고령화율 = 65세 이상 인구 / 전체 인구 × 100
elderly_population = sum(population_by_age_total[65:])

elderly_rate = (
    elderly_population / total_population * 100
    if total_population > 0
    else 0.0
)


# --------------------------------------------
# 아이 인구 계산
# --------------------------------------------
# 아이 인구는 0~14세로 정의합니다.
child_population = sum(population_by_age_total[:15])

child_rate = (
    child_population / total_population * 100
    if total_population > 0
    else 0.0
)


# --------------------------------------------
# 14. 지역 이름과 지표 카드 3개
# --------------------------------------------
st.subheader(
    f"📊 {selected_sido} · {selected_sigungu} · {selected_dong}"
)

# 세 카드를 같은 줄에 나란히 배치합니다.
metric1, metric2, metric3 = st.columns(3)

with metric1:
    st.metric(
        label="👥 총인구",
        value=f"{total_population:,}명",
    )

with metric2:
    if average_age is None:
        st.metric(
            label="🎂 평균연령",
            value="계산 불가",
        )
    else:
        st.metric(
            label="🎂 평균연령",
            value=f"{average_age:.1f}세",
        )

with metric3:
    # 고령화율이 20%를 초과하면 카드에 주의 표시를 붙입니다.
    if elderly_rate > 20:
        elderly_label = "⚠️ 고령화율 · 주의"
    else:
        elderly_label = "🌱 고령화율"

    st.metric(
        label=elderly_label,
        value=f"{elderly_rate:.1f}%",
        help=(
            "전체 인구 중 65세 이상 인구의 비율입니다. "
            "20%를 초과하면 주의 표시를 합니다."
        ),
    )

    if elderly_rate > 20:
        st.caption("⚠️ 고령화율이 20%를 초과합니다.")


# --------------------------------------------
# 15. Plotly 인구 피라미드 만들기
# --------------------------------------------
# 남성은 음수로 만들어 왼쪽에,
# 여성은 양수로 만들어 오른쪽에 표시합니다.
male_negative = [-value for value in male_values]

fig = go.Figure()

# 남성 인구 막대
fig.add_trace(
    go.Bar(
        name="남성",
        y=age_labels,
        x=male_negative,
        orientation="h",
        marker_color="#C87958",
        customdata=male_values,
        hovertemplate=(
            "%{y}<br>"
            "남성 인구: %{customdata:,.0f}명"
            "<extra></extra>"
        ),
    )
)

# 여성 인구 막대
fig.add_trace(
    go.Bar(
        name="여성",
        y=age_labels,
        x=female_values,
        orientation="h",
        marker_color="#E6B95E",
        customdata=female_values,
        hovertemplate=(
            "%{y}<br>"
            "여성 인구: %{customdata:,.0f}명"
            "<extra></extra>"
        ),
    )
)


# --------------------------------------------
# 16. 가로축 범위와 눈금 설정
# --------------------------------------------
# 좌우 범위를 동일하게 설정해 피라미드를 대칭으로 만듭니다.
max_population = max(
    max(male_values),
    max(female_values),
    1,
)

tick_step = max(1, math.ceil(max_population / 2))
axis_limit = tick_step * 2

tick_values = [
    -axis_limit,
    -tick_step,
    0,
    tick_step,
    axis_limit,
]

# 왼쪽의 음수도 눈금에는 양수 인구수로 표시합니다.
tick_text = [
    f"{abs(value):,}"
    for value in tick_values
]


# --------------------------------------------
# 17. 그래프 디자인
# --------------------------------------------
fig.update_layout(
    title={
        "text": "연령별 남녀 인구 피라미드",
        "x": 0.5,
        "xanchor": "center",
    },
    barmode="relative",
    bargap=0.08,
    height=1250,
    paper_bgcolor="#FFF9ED",
    plot_bgcolor="#FFF9ED",
    font={
        "family": "sans-serif",
        "size": 12,
        "color": "#4E3D2D",
    },
    legend={
        "title_text": "",
        "orientation": "h",
        "yanchor": "bottom",
        "y": 1.01,
        "xanchor": "right",
        "x": 1,
    },
    margin={
        "l": 100,
        "r": 40,
        "t": 100,
        "b": 75,
    },
)

# 가로축: 인구수
fig.update_xaxes(
    title_text="인구 수 (명)",
    range=[
        -axis_limit * 1.1,
        axis_limit * 1.1,
    ],
    tickmode="array",
    tickvals=tick_values,
    ticktext=tick_text,
    showgrid=True,
    gridcolor="#EADFCB",
    zeroline=True,
    zerolinecolor="#947C62",
    zerolinewidth=2,
)


# --------------------------------------------
# ★ 중요: 세로축 나이 순서 고정
# --------------------------------------------
# 나이 라벨을 0세부터 100세 이상까지 순서대로 지정합니다.
# categoryorder="array"와 categoryarray로 순서를 고정합니다.
#
# 축 전체를 뒤집는 autorange="reversed"는 사용하지 않습니다.
# 인구수 크기순 정렬도 사용하지 않습니다.
#
# 결과:
# 맨 아래 = 0세
# 맨 위 = 100세 이상
fig.update_yaxes(
    title_text="나이",
    categoryorder="array",
    categoryarray=age_labels,
    showgrid=False,
    tickfont={"size": 10},
)


# --------------------------------------------
# 18. 그래프 출력
# --------------------------------------------
st.plotly_chart(
    fig,
    use_container_width=True,
    config={
        "displaylogo": False,
        "responsive": True,
    },
)


# --------------------------------------------
# 19. 아이와 어르신 인구 비교 설명
# --------------------------------------------
st.markdown(
    "### 🧭 이 동네는 아이가 많은 편인가요, 어르신이 많은 편인가요?"
)

if total_population == 0:
    st.write(
        "이 동네의 인구 데이터가 없어 "
        "아이와 어르신의 비율을 비교할 수 없습니다."
    )

elif child_population > elderly_population:
    st.write(
        f"이 동네는 65세 이상 어르신({elderly_population:,}명)보다 "
        f"0~14세 아이({child_population:,}명)가 더 많아, "
        "상대적으로 아이가 많은 편이에요."
    )

elif elderly_population > child_population:
    st.write(
        f"이 동네는 0~14세 아이({child_population:,}명)보다 "
        f"65세 이상 어르신({elderly_population:,}명)이 더 많아, "
        "상대적으로 어르신이 많은 편이에요."
    )

else:
    st.write(
        f"이 동네는 0~14세 아이와 65세 이상 어르신이 "
        f"각각 {child_population:,}명으로 같아요."
    )


# --------------------------------------------
# 20. 자료 및 계산 기준 안내
# --------------------------------------------
st.caption(
    "자료: 지정된 인구 CSV 데이터 · "
    f"표시 연도: {latest_year}년 · "
    "평균연령 계산에서 100세 이상은 100세로 가정했습니다."
)
