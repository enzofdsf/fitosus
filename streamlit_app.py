# FitoSUS — chatbot sobre plantas medicinais e fitoterápicos no SUS
# Feito para rodar no Streamlit Community Cloud. A chave do Gemini fica nos
# "Secrets" do app, na linha: GEMINI_API_KEY = "sua-chave"

import json
import os
import re

import requests
import streamlit as st
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from pypdf import PdfReader

MODELO = "gemini-3.5-flash-lite"
PASTA = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# 1. LISTA DE FONTES
#    "sempre": True  → vai em toda pergunta (páginas curtas do gov.br)
#    "sempre": False → só vai quando a seleção achar que a pergunta precisa
#    "assunto" é o que a seleção lê para decidir se o documento é necessário.
# ---------------------------------------------------------------------------
FONTES = [
    {
        "id": "pagina_principal",
        "titulo": "Plantas Medicinais e Fitoterápicos (Ministério da Saúde)",
        "url": "https://www.gov.br/saude/pt-br/composicao/sectics/plantas-medicinais-e-fitoterapicos",
        "sempre": True,
    },
    {
        "id": "no_sus",
        "titulo": "Plantas medicinais e fitoterápicos no SUS (Ministério da Saúde)",
        "url": "https://www.gov.br/saude/pt-br/composicao/sectics/plantas-medicinais-e-fitoterapicos/plantas-medicinais-e-fitoterapicos-no-sus",
        "sempre": True,
    },
    {
        "id": "renisus",
        "titulo": "Tabela ReniSUS — Relação Nacional de Plantas Medicinais de Interesse ao SUS",
        "url": "https://www.gov.br/saude/pt-br/composicao/sectics/plantas-medicinais-e-fitoterapicos/plantas-medicinais-e-fitoterapicos-no-sus/tabela-renisus",
        "sempre": True,
    },
    {
        "id": "incorporacoes",
        "titulo": "Incorporações de fitoterápicos no SUS (Ministério da Saúde)",
        "url": "https://www.gov.br/saude/pt-br/composicao/sectics/plantas-medicinais-e-fitoterapicos/plantas-medicinais-e-fitoterapicos-no-sus/incorporacoes-no-sus",
        "sempre": True,
    },
    {
        "id": "ppnpmf_pagina",
        "titulo": "Política e Programa Nacional de Plantas Medicinais e Fitoterápicos (página do Ministério da Saúde)",
        "url": "https://www.gov.br/saude/pt-br/composicao/sectics/plantas-medicinais-e-fitoterapicos/ppnpmf",
        "sempre": True,
    },
    {
        "id": "ppnpmf_livro",
        "titulo": "Política e Programa Nacional de Plantas Medicinais e Fitoterápicos (livro, Ministério da Saúde, 2016)",
        "url": "https://bvsms.saude.gov.br/bvs/publicacoes/politica_programa_nacional_plantas_medicinais_fitoterapicos.pdf",
        "arquivo": "politica_programa_nacional_plantas_medicinais_fitoterapicos.pdf",
        "curto": "livro da Política e Programa Nacional",
        "sempre": False,
        "assunto": "Texto completo da Política Nacional (PNPMF) e do Programa Nacional de Plantas "
                   "Medicinais e Fitoterápicos: diretrizes, objetivos, ações, gestores, legislação, "
                   "decretos e portarias, cadeia produtiva, pesquisa, regulamentação, financiamento, "
                   "conhecimento tradicional, formação de profissionais, monitoramento e avaliação.",
    },
    {
        "id": "andiroba",
        "titulo": "Informações Sistematizadas da Relação Nacional de Plantas Medicinais de Interesse ao SUS — "
                  "Carapa guianensis Aubl. (andiroba) (Ministério da Saúde, 2021)",
        "url": "https://bvsms.saude.gov.br/bvs/publicacoes/informacoes_sistematizadas_relacao_carapa_guianensis.pdf",
        "arquivo": "informacoes_sistematizadas_relacao_carapa_guianensis.pdf",
        "curto": "monografia da andiroba (Carapa guianensis)",
        "sempre": False,
        "assunto": "Monografia sobre a espécie Carapa guianensis Aubl. (Meliaceae), conhecida como "
                   "andiroba: identificação botânica, distribuição, usos tradicionais, composição "
                   "química, estudos farmacológicos, toxicológicos e clínicos, segurança e regulação.",
    },
    {
        "id": "maracuja",
        "titulo": "Informações Sistematizadas da Relação Nacional de Plantas Medicinais de Interesse ao SUS — "
                  "Passiflora incarnata L. (maracujá-vermelho) (Ministério da Saúde, 2021)",
        "url": "https://bvsms.saude.gov.br/bvs/publicacoes/informacoes_sistematizadas_relacao_maracuja_vermelho.pdf",
        "arquivo": "informacoes_sistematizadas_relacao_maracuja_vermelho.pdf",
        "curto": "monografia do maracujá-vermelho (Passiflora incarnata)",
        "sempre": False,
        "assunto": "Monografia sobre a espécie Passiflora incarnata Linnaeus (Passifloraceae), conhecida "
                   "como maracujá-vermelho ou passiflora: identificação botânica, distribuição, usos "
                   "tradicionais, composição química, estudos farmacológicos, toxicológicos e clínicos, "
                   "segurança e regulação. Também útil para perguntas sobre o gênero Passiflora.",
    },
]

# Nos PDFs do Ministério, a página impressa no rodapé = página do arquivo - 1
DESLOCAMENTO_PAGINA = 1

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


# ---------------------------------------------------------------------------
# 2. LEITURA DAS FONTES (roda uma vez, quando o app liga)
# ---------------------------------------------------------------------------
def texto_de_html(html):
    soup = BeautifulSoup(html, "html.parser")
    area = soup.find(id="content-core") or soup.find(id="content") or soup.body or soup
    for lixo in area.find_all(["script", "style", "nav", "header", "footer", "form"]):
        lixo.decompose()
    for tabela in area.find_all("table"):
        linhas = []
        for tr in tabela.find_all("tr"):
            celulas = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if any(celulas):
                linhas.append(" | ".join(celulas))
        tabela.replace_with("\n" + "\n".join(linhas) + "\n")
    return re.sub(r"\n{3,}", "\n\n", area.get_text("\n", strip=True))


def texto_de_pdf(caminho):
    leitor = PdfReader(caminho)
    paginas = []
    for i, pagina in enumerate(leitor.pages, start=1):
        t = (pagina.extract_text() or "").strip()
        if not t:
            continue
        impressa = i - DESLOCAMENTO_PAGINA
        rotulo = f"[página {impressa}]" if impressa >= 1 else "[capa]"
        paginas.append(f"{rotulo}\n{t}")
    return "\n\n".join(paginas)


@st.cache_resource(show_spinner="Carregando as fontes oficiais...")
def carregar_fontes():
    """Lê todas as fontes uma única vez (fica guardado enquanto o app estiver ligado)."""
    carregadas, falhas = [], []
    for original in FONTES:
        f = dict(original)
        try:
            if "arquivo" in f:
                f["texto"] = texto_de_pdf(os.path.join(PASTA, f["arquivo"]))
            else:
                try:
                    r = requests.get(f["url"], headers=HEADERS, timeout=60)
                    r.raise_for_status()
                    f["texto"] = texto_de_html(r.text)
                except Exception:
                    # Plano B: se o site não responder, usa uma cópia salva no projeto (ex.: renisus.txt)
                    reserva = os.path.join(PASTA, f"{f['id']}.txt")
                    if not os.path.exists(reserva):
                        raise
                    f["texto"] = open(reserva, encoding="utf-8").read()
            if not f["texto"].strip():
                raise ValueError("nenhum texto encontrado")
            carregadas.append(f)
            print(f"OK   {f['id']}: {len(f['texto']):,} caracteres")
        except Exception as e:
            falhas.append(f["titulo"])
            print(f"ERRO {f['id']}: {e}")
    return carregadas, falhas


@st.cache_resource
def cliente():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


# ---------------------------------------------------------------------------
# 3. SELEÇÃO INTELIGENTE: decide quais documentos grandes a pergunta precisa
#    Na dúvida, manda mais. Se der qualquer erro, manda todos.
# ---------------------------------------------------------------------------
INSTRUCAO_SELECAO = """Você escolhe quais documentos um assistente precisa ler para responder
a última pergunta de um profissional de saúde sobre plantas medicinais e fitoterápicos no SUS.

Documentos disponíveis:
{lista}

Regras:
- Considere o histórico: se a pergunta for uma continuação ("e a dose?", "e os efeitos adversos?"),
  escolha os documentos do assunto que estava sendo discutido.
- Reconheça as espécies pelo nome popular, nome científico ou gênero.
- NA DÚVIDA, INCLUA o documento. É muito pior deixar de fora um documento útil do que incluir um desnecessário.
- Se nenhum destes documentos tiver relação com a pergunta, devolva uma lista vazia.

Responda apenas em JSON, no formato: {{"documentos": ["id1", "id2"]}}"""


def selecionar(opcionais, historico_recente, pergunta):
    if not opcionais:
        return []
    lista = "\n".join(f'- id "{f["id"]}": {f["assunto"]}' for f in opcionais)
    conversa = "\n".join(f"{papel}: {texto[:600]}" for papel, texto in historico_recente)
    prompt = f"Histórico recente:\n{conversa or '(início da conversa)'}\n\nÚltima pergunta: {pergunta}"
    try:
        resp = cliente().models.generate_content(
            model=MODELO,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=INSTRUCAO_SELECAO.format(lista=lista),
                temperature=0,
                response_mime_type="application/json",
            ),
        )
        ids = json.loads(resp.text).get("documentos", [])
        return [f for f in opcionais if f["id"] in ids]
    except Exception as e:
        print(f"Seleção falhou ({e}); usando todos os documentos.")
        return list(opcionais)


# ---------------------------------------------------------------------------
# 4. RESPOSTA: monta as regras + documentos escolhidos e pergunta ao Gemini
# ---------------------------------------------------------------------------
REGRAS = """Você é o FitoSUS, um assistente de consulta para profissionais de saúde sobre plantas
medicinais e fitoterápicos no Sistema Único de Saúde (SUS). Seu papel é resumir o material oficial
do Ministério da Saúde para estudo e capacitação.

Regras:
1. Responda SOMENTE com base nas fontes abaixo. Se a informação não estiver nelas, diga claramente
   que não a encontrou nas fontes oficiais disponíveis e, se fizer sentido, sugira reformular a pergunta.
2. Seja técnico, claro e resumido. Use listas quando ajudarem a leitura.
3. Cite as fontes usadas ao final, no formato:
   Fonte: <título do documento>, p. <página> — <link>
   As páginas dos PDFs já estão marcadas no texto como [página N]; use esse número.
   Para as páginas do site do Ministério, cite o título e o link (sem página).
4. Nunca invente espécies, doses, portarias, datas ou números. Ao citar doses ou indicações,
   reproduza exatamente o que a fonte diz.
5. Responda em português do Brasil.

=== FONTES OFICIAIS ===
{fontes}"""


def gerar_resposta(fontes, historico, pergunta):
    """Devolve a resposta em pedaços, para ela aparecer aos poucos na tela."""
    pares = [("user" if m["role"] == "user" else "model", m["content"]) for m in historico]
    opcionais = [f for f in fontes if not f["sempre"]]

    escolhidos = selecionar(opcionais, pares[-4:], pergunta)
    usados = [f for f in fontes if f["sempre"]] + escolhidos
    texto_fontes = "\n\n".join(
        f"<fonte titulo='{f['titulo']}' link='{f['url']}'>\n{f['texto']}\n</fonte>" for f in usados
    )

    contents = [types.Content(role=p, parts=[types.Part(text=t)]) for p, t in pares]
    contents.append(types.Content(role="user", parts=[types.Part(text=pergunta)]))

    try:
        for parte in cliente().models.generate_content_stream(
            model=MODELO,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=REGRAS.format(fontes=texto_fontes), temperature=0.2
            ),
        ):
            if parte.text:
                yield parte.text
        nomes = "; ".join(f["curto"] for f in escolhidos) or "nenhum"
        yield f"\n\n---\n*Documentos consultados além das páginas do Ministério: {nomes}.*"
    except Exception as e:
        yield f"Desculpe, não consegui consultar o modelo agora. Tente de novo em instantes.\n\n(Erro: {e})"


# ---------------------------------------------------------------------------
# 5. TELA DO CHAT
# ---------------------------------------------------------------------------
EXEMPLOS = [
    "O que é a ReniSUS?",
    "Quais fitoterápicos já foram incorporados ao SUS?",
    "Quais são as diretrizes da Política Nacional de Plantas Medicinais e Fitoterápicos?",
    "O que os estudos clínicos dizem sobre a Passiflora incarnata?",
    "Quais são os usos tradicionais da andiroba?",
]

st.set_page_config(page_title="FitoSUS", page_icon="🌿")
st.title("🌿 FitoSUS")
st.caption(
    "Consulta resumida ao material oficial do Ministério da Saúde sobre plantas medicinais e "
    "fitoterápicos no SUS, para estudo e capacitação. Toda resposta cita o documento e a página "
    "de origem. Confira sempre na fonte original. Este assistente não substitui a avaliação clínica."
)

fontes, falhas = carregar_fontes()

if "mensagens" not in st.session_state:
    st.session_state.mensagens = []

with st.sidebar:
    if st.button("🗑️ Nova conversa", use_container_width=True):
        st.session_state.mensagens = []
        st.rerun()
    st.markdown("**Fontes carregadas**")
    for f in fontes:
        st.markdown(f"- [{f['titulo']}]({f['url']})")
    for titulo in falhas:
        st.warning(f"Não foi possível carregar: {titulo}")

# Mostra a conversa até agora
for m in st.session_state.mensagens:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

pergunta = st.chat_input("Digite sua pergunta...")

# Perguntas de exemplo (só aparecem com a conversa vazia)
if not st.session_state.mensagens and not pergunta:
    area_exemplos = st.empty()
    with area_exemplos.container():
        st.markdown("**Experimente perguntar:**")
        for exemplo in EXEMPLOS:
            if st.button(exemplo, use_container_width=True):
                pergunta = exemplo
    if pergunta:
        area_exemplos.empty()

if pergunta:
    historico = list(st.session_state.mensagens)
    st.session_state.mensagens.append({"role": "user", "content": pergunta})
    with st.chat_message("user"):
        st.markdown(pergunta)
    with st.chat_message("assistant"):
        resposta = st.write_stream(gerar_resposta(fontes, historico, pergunta))
    st.session_state.mensagens.append({"role": "assistant", "content": resposta})
