"""Preparacao de dados do modelo de risco de alagamento.

Este modulo e a unica fonte da logica de preparacao: o notebook de EDA, o treino, o DAG do Airflow e a API de
inferencia devem importa-lo, para que treino e producao enxerguem exatamente as mesmas variaveis.
"""
import numpy as np
import pandas as pd

ALVO_PADRAO = "alagou_estrito"
FAIXAS_CHUVA = [-0.01, 1, 10, 30, 50, 1000]          # mm/dia
DIAS_SEM_EVENTO = 3650                               # "nunca houve evento": equivale a 10 anos
PROPENSAO_NEUTRA = 1.0                               # bairro sem historico: nem mais nem menos propenso

# colunas que nao entram como variavel explicativa
EXCLUIR = ["bairro", "regional", "data", "ano", "alagou", "alagou_estrito",
           "n_registros_alag", "n_registros_alag_estrito",          # contam o proprio alvo (vazamento)
           "horas_validas_dia", "n_pontos_grade", "local_casado",   # controle de qualidade
           "lat_centro", "lon_centro"]                              # identificam o bairro (decorar lugares)
DATAS_IMPRESSAO_DIGITAL = ["fase_lunar", "sizigia", "dia_do_ano_sin", "dia_do_ano_cos"]
DEPENDEM_CHUVA_DO_DIA = ["chuva_dia_mm", "chuva_max_1h_mm", "mare_na_hora_pico_chuva_m", "mare_subindo_na_hora_pico"]

COLS_LOG = ["chuva_dia_mm", "chuva_max_1h_mm", "chuva_d1_mm", "chuva_ult3d_mm",
            "chuva_ult7d_mm", "chuva_ult15d_mm", "chuva_ult30d_mm"]
COLS_DIAS = ["dias_desde_ultimo_alag", "dias_desde_ultimo_alag_estrito"]
COLS_MARE_PICO = ["mare_na_hora_pico_chuva_m", "mare_subindo_na_hora_pico"]

# faixas fisicamente plausiveis, usadas na checagem de qualidade
LIMITES = {"chuva_dia_mm": (0, 400), "chuva_max_1h_mm": (0, 150), "mare_max_dia_m": (-2.5, 2.5),
           "mare_min_dia_m": (-2.5, 2.5), "alt_media_m": (-10, 150), "pct_pontos_abaixo_5m": (0, 100),
           "pct_area_faixa_marginal": (0, 100), "fase_lunar": (0, 1)}


def carregar_dataset(caminho):
    df = pd.read_csv(caminho, parse_dates=["data"])
    df["ano"] = df["data"].dt.year
    return df


def selecionar_linhas(df):
    """Mantem so os dias com chuva medida: sem ela nao ha o que prever."""
    return df[df["chuva_dia_mm"].notna()].reset_index(drop=True)


def lista_features(colunas, cenario="A"):
    """Cenario A: chuva do dia conhecida. Cenario B: sem ela. Nunca inclui variaveis de impressao digital de data."""
    f = [c for c in colunas if c not in EXCLUIR and c not in DATAS_IMPRESSAO_DIGITAL]
    if cenario == "B":
        f = [c for c in f if c not in DEPENDEM_CHUVA_DO_DIA]
    return f


def verificar_qualidade(df):
    """Checagens simples de integridade; devolve um dicionario (usado no notebook e no DAG)."""
    res = {"linhas": int(len(df)), "duplicatas_bairro_data": int(df.duplicated(["bairro", "data"]).sum())}
    res["valores_fora_do_limite"] = {c: int(((df[c] < lo) | (df[c] > hi)).sum())
                                     for c, (lo, hi) in LIMITES.items() if c in df}
    if {"alagou", "alagou_estrito"} <= set(df.columns):
        res["alvo_fora_de_0_1"] = int((~df[["alagou", "alagou_estrito"]].isin([0, 1])).any(axis=1).sum())
        res["estrito_sem_amplo"] = int(((df["alagou_estrito"] == 1) & (df["alagou"] == 0)).sum())
    return res


# ------------------------------------------------------------------ propensao do bairro (codificacao do bairro)
def tabela_propensao(df, alvo, anos):
    """Eventos do bairro nos 'anos', suavizados e relativos a media dos bairros."""
    ev = df.loc[df["ano"].isin(anos)].groupby("bairro")[alvo].sum()
    return (ev + 1) / (ev.mean() + 1)


def aplicar_propensao(df, tabela):
    return df["bairro"].map(tabela).fillna(PROPENSAO_NEUTRA)


def propensao_treino(df, alvo, anos_treino):
    """Cada ano de treino recebe a propensao calculada SEM ele, para o modelo nao ler o proprio rotulo.
    Linhas fora dos anos de treino (validacao/teste/novas) usam todos os anos de treino."""
    saida = pd.Series(np.nan, index=df.index, dtype=float)
    todos = tabela_propensao(df, alvo, anos_treino)
    fora = ~df["ano"].isin(anos_treino)
    saida[fora] = df.loc[fora, "bairro"].map(todos)
    for s in anos_treino:
        tabela = tabela_propensao(df, alvo, [a for a in anos_treino if a != s])
        m = df["ano"] == s
        saida[m] = df.loc[m, "bairro"].map(tabela)
    return saida.fillna(PROPENSAO_NEUTRA)


# ------------------------------------------------------------------ transformacao (ajustada so no treino)
class Preparador:
    """Tratamento de ausentes, transformacao log, imputacao pela mediana e padronizacao.

    fit() usa apenas os dados de treino; transform() aplica o mesmo ajuste a qualquer outro dado
    (validacao, teste ou novas leituras vindas do sistema embarcado).
    """

    def __init__(self, log=True, escala=True, imputar=True):
        self.log, self.escala, self.imputar = log, escala, imputar

    def _transformar(self, X):
        X = X.copy()
        for c in COLS_DIAS:                           # ausencia estrutural: nunca houve evento antes
            if c in X:
                X[c + "_nunca"] = X[c].isna().astype(int)
                X[c] = X[c].fillna(DIAS_SEM_EVENTO)
                if self.log:
                    X[c] = np.log1p(X[c])
        if self.log:                                  # chuvas sao muito assimetricas
            for c in COLS_LOG:
                if c in X:
                    X[c] = np.log1p(X[c].clip(lower=0))
        if COLS_MARE_PICO[0] in X:                    # sem chuva no dia nao existe hora de pico
            X["sem_chuva_no_dia"] = X[COLS_MARE_PICO[0]].isna().astype(int)
            for c in COLS_MARE_PICO:
                if c in X:
                    X[c] = X[c].fillna(0)
        return X

    def fit(self, X):
        Xt = self._transformar(X)
        self.colunas_ = list(Xt.columns)
        self.medianas_ = Xt.median()
        Xi = Xt.fillna(self.medianas_)
        self.media_ = Xi.mean()
        self.desvio_ = Xi.std(ddof=0).replace(0, 1.0)
        return self

    def transform(self, X):
        Xt = self._transformar(X).reindex(columns=self.colunas_)
        if self.imputar:
            Xt = Xt.fillna(self.medianas_)
        if self.escala:
            Xt = (Xt - self.media_) / self.desvio_
        return Xt

    def fit_transform(self, X):
        return self.fit(X).transform(X)
