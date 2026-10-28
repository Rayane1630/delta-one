"""
INDICE À DÉCRÉMENT
==================

Pourquoi ces indices existent
-----------------------------
Une banque qui vend un produit structuré sur un indice classique (prix ou
Net Total Return) garde un RISQUE DE DIVIDENDE : si les dividendes futurs
baissent, le forward monte et sa couverture perd de la valeur.

Un indice à décrément part du Net Total Return (dividendes nets réinvestis)
et retire chaque jour un dividende synthétique FIXÉ À L'AVANCE :
    - décrément en points    : I_t = I_{t-1} x NTR_t / NTR_{t-1} - D x jours / 365
    - décrément en pourcentage : I_t = I_{t-1} x (NTR_t / NTR_{t-1} - d x jours / 365)

Le dividende "retiré" est connu dès l'émission : plus de risque de dividende
pour la banque. Le décrément est en général supérieur aux dividendes
réalisés, ce qui fait baisser le forward et rend les options (donc la
protection du capital) moins chères : c'est ce qui finance la formule
de protection des fonds structurés.

FICHIER EXCEL À CRÉER POUR UTILISER LE CODE
-------------------------------------------
Nom du fichier : historique_indices.xlsx
Emplacement    : le dossier indiqué dans DOSSIER_DONNEES ci-dessous

Onglet "Historique"  (en-têtes en ligne 1, données à partir de la ligne 2)
    Colonne A : Date
    Colonne B : Indice_Prix  (ex. SX5E Index)
    Colonne C : Indice_NTR   (ex. SX5T Index, dividendes nets réinvestis)

Lancement
---------
    python indice_decrement.py          -> lit le fichier Excel
    python indice_decrement.py --demo   -> données fictives
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# PARAMÈTRES À MODIFIER
# ---------------------------------------------------------------------------

DOSSIER_DONNEES = r"XXXXXXXXXXXXXXXXXXXXXXXX"
NOM_FICHIER = "historique_indices.xlsx"

DECREMENT_POINTS = 50.0        # décrément fixe en points d'indice par an
DECREMENT_POURCENT = 0.05      # décrément en % par an
BASE_JOURS = 365.0


# ---------------------------------------------------------------------------
# 1. DONNÉES
# ---------------------------------------------------------------------------

def lire_historique(chemin):
    chemin = Path(chemin)
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}\n"
                                "Vérifie DOSSIER_DONNEES, ou lance avec --demo.")
    df = pd.read_excel(chemin, sheet_name="Historique", usecols="A:C")
    df.columns = ["Date", "Indice_Prix", "Indice_NTR"]
    return df.dropna().sort_values("Date").set_index("Date")


def historique_demo():
    """
    Indice prix simulé (jours ouvrés) + dividendes concentrés au printemps,
    comme sur l'Euro Stoxx 50. Le NTR réinvestit les dividendes nets.
    """
    rng = np.random.default_rng(5)
    dates = pd.bdate_range("2019-01-02", "2026-10-28")
    n = len(dates)
    vol, derive = 0.19, 0.06
    rendements = derive / 252 - 0.5 * vol ** 2 / 252 + vol / np.sqrt(252) * rng.standard_normal(n - 1)
    prix = 3000 * np.exp(np.concatenate([[0], np.cumsum(rendements)]))

    # Rendement du dividende annuel net ~3 %, versé surtout d'avril à juin
    poids_mois = np.array([1, 1, 3, 10, 14, 8, 3, 2, 2, 2, 1, 1], dtype=float)
    poids_mois /= poids_mois.sum()
    jours_par_mois = pd.Series(dates.month).map(pd.Series(dates.month).value_counts() / len(set(dates.year)))
    taux_jour = 0.03 * poids_mois[dates.month - 1] / jours_par_mois.to_numpy()

    ntr = np.empty(n)
    ntr[0] = prix[0]
    dividendes = prix * taux_jour
    for t in range(1, n):
        ntr[t] = ntr[t - 1] * (prix[t] + dividendes[t]) / prix[t - 1]

    return pd.DataFrame({"Indice_Prix": prix, "Indice_NTR": ntr}, index=dates)


# ---------------------------------------------------------------------------
# 2. CALCUL DES INDICES À DÉCRÉMENT
# ---------------------------------------------------------------------------

def calculer_decrements(hist):
    """Construit les deux indices à décrément, en base 100 du NTR au départ."""
    perf_ntr = hist["Indice_NTR"] / hist["Indice_NTR"].shift(1)
    jours = hist.index.to_series().diff().dt.days

    base = hist["Indice_Prix"].iloc[0]
    dec_pts = [base]
    dec_pct = [base]
    for t in range(1, len(hist)):
        fraction = jours.iloc[t] / BASE_JOURS
        dec_pts.append(dec_pts[-1] * perf_ntr.iloc[t] - DECREMENT_POINTS * fraction)
        dec_pct.append(dec_pct[-1] * (perf_ntr.iloc[t] - DECREMENT_POURCENT * fraction))

    res = hist.copy()
    res[f"Decrement_{DECREMENT_POINTS:g}pts"] = dec_pts
    res[f"Decrement_{DECREMENT_POURCENT * 100:g}pct"] = dec_pct
    return res


def statistiques(res):
    """Performance annualisée, volatilité et rendement implicite du dividende retiré."""
    annees = (res.index[-1] - res.index[0]).days / BASE_JOURS
    stats = []
    for col in res.columns:
        serie = res[col]
        rendements = np.log(serie / serie.shift(1)).dropna()
        stats.append({
            "Indice": col,
            "Perf. annualisée": (serie.iloc[-1] / serie.iloc[0]) ** (1 / annees) - 1,
            "Volatilité": rendements.std() * np.sqrt(252),
            "Plus bas / départ": serie.min() / serie.iloc[0] - 1,
        })
    tableau = pd.DataFrame(stats).set_index("Indice")

    # Dividende réalisé = écart de performance NTR vs prix
    div_realise = tableau.loc["Indice_NTR", "Perf. annualisée"] - tableau.loc["Indice_Prix", "Perf. annualisée"]
    return tableau, div_realise


# ---------------------------------------------------------------------------
# 3. GRAPHIQUE
# ---------------------------------------------------------------------------

def tracer(res):
    base = res.iloc[0]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    styles = {"Indice_Prix": ("#7F7F7F", "-"), "Indice_NTR": ("#1F3864", "-")}
    for col in res.columns:
        couleur, trait = styles.get(col, (None, "--"))
        ax.plot(res.index, res[col] / base[col] * 100, trait, color=couleur, lw=1.4, label=col)
    ax.set_title("Indice prix, Net Total Return et indices à décrément (base 100)")
    ax.set_ylabel("Base 100")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    sortie = Path(__file__).with_name("indices_decrement.png")
    fig.savefig(sortie, dpi=150)
    print(f"\nGraphique enregistré : {sortie}")
    plt.show()


def main():
    if "--demo" in sys.argv:
        print("Mode démo : données fictives.")
        hist = historique_demo()
    else:
        hist = lire_historique(Path(DOSSIER_DONNEES) / NOM_FICHIER)

    res = calculer_decrements(hist)
    tableau, div_realise = statistiques(res)

    pd.options.display.float_format = "{:.2%}".format
    print("\n", tableau)
    print(f"\nDividende net réalisé (NTR - prix) : {div_realise:.2%} par an")
    print(f"Décrément en % : {DECREMENT_POURCENT:.2%} par an "
          f"-> écart de {DECREMENT_POURCENT - div_realise:+.2%} au détriment de l'investisseur,")
    print("   en échange d'options moins chères (forward plus bas) et sans risque de dividende pour la banque.")
    tracer(res)


if __name__ == "__main__":
    main()
