"""
RÉPLICATION PHYSIQUE D'UN INDICE AVEC REBALANCEMENT TRIMESTRIEL
===============================================================

Objectif
--------
Un fonds (ou un ETF) en réplication physique détient réellement les actions
de l'indice. À chaque rebalancement trimestriel, l'indice change ses poids :
le gérant doit acheter / vendre pour coller aux nouveaux poids.

Le script :
    1. calcule l'indice de référence (poids cibles, rebalancé chaque trimestre) ;
    2. simule le portefeuille réel : nombre d'actions ENTIER, frais de
       transaction à chaque rebalancement, poids qui dérivent entre deux dates ;
    3. mesure la qualité de la réplication :
           tracking difference = perf fonds - perf indice
           tracking error      = volatilité annualisée de l'écart quotidien
       et le turnover (volume échangé à chaque rebalancement).

FICHIER EXCEL À CRÉER POUR UTILISER LE CODE
-------------------------------------------
Nom du fichier : donnees_replication.xlsx
Emplacement    : le dossier indiqué dans DOSSIER_DONNEES ci-dessous

Onglet "Prix"  (en-têtes en ligne 1)
    Colonne A        : Date
    Colonnes B, C... : un cours de clôture par action, nom de l'action en en-tête

Onglet "Poids"  (en-têtes en ligne 1)
    Colonne A        : Date de rebalancement
    Colonnes B, C... : poids cible de chaque action (mêmes en-têtes que "Prix",
                       somme des poids = 1 sur chaque ligne)

Lancement
---------
    python replication_indice.py          -> lit le fichier Excel
    python replication_indice.py --demo   -> données fictives (10 actions)
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
NOM_FICHIER = "donnees_replication.xlsx"

ENCOURS_INITIAL = 50_000_000.0   # taille du fonds en euros
FRAIS_TRANSACTION = 0.0010       # 10 bp sur chaque montant acheté ou vendu


# ---------------------------------------------------------------------------
# 1. DONNÉES
# ---------------------------------------------------------------------------

def lire_donnees(chemin):
    chemin = Path(chemin)
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}\n"
                                "Vérifie DOSSIER_DONNEES, ou lance avec --demo.")
    prix = pd.read_excel(chemin, sheet_name="Prix", index_col=0, parse_dates=True).sort_index()
    poids = pd.read_excel(chemin, sheet_name="Poids", index_col=0, parse_dates=True).sort_index()
    poids = poids.div(poids.sum(axis=1), axis=0)       # sécurité : somme = 100 %
    return prix, poids


def donnees_demo():
    """10 actions corrélées, poids cibles qui changent à chaque trimestre."""
    rng = np.random.default_rng(12)
    dates = pd.bdate_range("2024-01-02", "2026-10-28")
    noms = [f"ACTION_{i:02d}" for i in range(1, 11)]
    n, k = len(dates), len(noms)

    vols = rng.uniform(0.18, 0.35, k)
    facteur = rng.standard_normal(n)                    # facteur marché commun
    bruit = rng.standard_normal((n, k))
    z = 0.6 * facteur[:, None] + 0.8 * bruit
    rendements = 0.05 / 252 - 0.5 * vols ** 2 / 252 + vols / np.sqrt(252) * z
    prix = pd.DataFrame(rng.uniform(20, 300, k) * np.exp(np.cumsum(rendements, axis=0)),
                        index=dates, columns=noms)

    # Rebalancement le 3e vendredi de mars, juin, septembre, décembre
    dates_rebal = [prix.index[0]]
    for annee in range(2024, 2027):
        for mois in (3, 6, 9, 12):
            vendredis = pd.date_range(f"{annee}-{mois:02d}-01", periods=31, freq="D")
            vendredis = vendredis[(vendredis.weekday == 4) & (vendredis.month == mois)]
            d = vendredis[2]
            if prix.index[0] < d <= prix.index[-1]:
                dates_rebal.append(prix.index[prix.index.get_indexer([d], method="bfill")[0]])

    poids = pd.DataFrame(rng.dirichlet(np.full(k, 8.0), len(dates_rebal)),
                         index=dates_rebal, columns=noms)
    return prix, poids


# ---------------------------------------------------------------------------
# 2. INDICE DE RÉFÉRENCE ET PORTEFEUILLE RÉPLIQUANT
# ---------------------------------------------------------------------------

def simuler(prix, poids):
    """
    Indice  : poids cibles appliqués exactement, sans frais, quantités fractionnaires.
    Fonds   : quantités entières, frais sur chaque transaction.
    """
    rebal = set(poids.index)
    rend = prix.pct_change().fillna(0)

    indice = [100.0]
    poids_indice = poids.iloc[0].to_numpy()

    quantites = np.zeros(prix.shape[1])
    cash = ENCOURS_INITIAL
    valeur_fonds, journal = [], []

    for t, date in enumerate(prix.index):
        cours = prix.loc[date].to_numpy()

        # --- Indice : on fait évoluer les poids avec les cours
        if t > 0:
            r = rend.loc[date].to_numpy()
            indice.append(indice[-1] * (1 + poids_indice @ r))
            poids_indice = poids_indice * (1 + r) / (1 + poids_indice @ r)

        # --- Rebalancement
        if date in rebal:
            cibles = poids.loc[date].to_numpy()
            poids_indice = cibles.copy()

            valeur = cash + quantites @ cours
            # On réserve d'abord le montant des frais pour ne jamais être à découvert :
            # 1er passage pour estimer les frais, 2e passage avec la valeur nette de frais
            frais = 0.0
            for _ in range(2):
                nouvelles_qte = np.floor((valeur - frais) * cibles / cours)   # actions entières
                echanges = (nouvelles_qte - quantites) * cours
                frais = FRAIS_TRANSACTION * np.abs(echanges).sum()
            cash -= echanges.sum() + frais
            quantites = nouvelles_qte
            journal.append({"Date": date.date(), "Turnover": np.abs(echanges).sum() / valeur,
                            "Frais (EUR)": frais, "Cash résiduel": cash / valeur})

        valeur_fonds.append(cash + quantites @ cours)

    res = pd.DataFrame({"Indice": indice,
                        "Fonds": np.array(valeur_fonds) / ENCOURS_INITIAL * 100},
                       index=prix.index)
    return res, pd.DataFrame(journal).set_index("Date")


def mesures(res):
    annees = (res.index[-1] - res.index[0]).days / 365.0
    perf = (res.iloc[-1] / res.iloc[0]) ** (1 / annees) - 1
    ecart_jour = res["Fonds"].pct_change() - res["Indice"].pct_change()
    return {
        "Perf. annualisée indice": perf["Indice"],
        "Perf. annualisée fonds": perf["Fonds"],
        "Tracking difference (par an)": perf["Fonds"] - perf["Indice"],
        "Tracking error (annualisée)": ecart_jour.std() * np.sqrt(252),
    }


# ---------------------------------------------------------------------------
# 3. GRAPHIQUE
# ---------------------------------------------------------------------------

def tracer(res, poids):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True,
                                   gridspec_kw={"height_ratios": [2, 1]})
    ax1.plot(res.index, res["Indice"], color="#7F7F7F", lw=1.5, label="Indice")
    ax1.plot(res.index, res["Fonds"], color="#1F3864", lw=1.2, ls="--", label="Fonds répliquant")
    for d in poids.index[1:]:
        ax1.axvline(d, color="#C00000", lw=0.6, alpha=0.4)
    ax1.set_title("Réplication physique : fonds vs indice (lignes rouges = rebalancements)")
    ax1.set_ylabel("Base 100")
    ax1.legend()
    ax1.grid(alpha=0.3)

    ecart_bp = (res["Fonds"] / res["Indice"] - 1) * 10_000
    ax2.plot(res.index, ecart_bp, color="#C00000", lw=1)
    ax2.axhline(0, color="black", lw=0.6)
    ax2.set_ylabel("Écart cumulé (bp)")
    ax2.grid(alpha=0.3)
    fig.tight_layout()

    sortie = Path(__file__).with_name("replication_indice.png")
    fig.savefig(sortie, dpi=150)
    print(f"\nGraphique enregistré : {sortie}")
    plt.show()


def main():
    if "--demo" in sys.argv:
        print("Mode démo : données fictives.")
        prix, poids = donnees_demo()
    else:
        prix, poids = lire_donnees(Path(DOSSIER_DONNEES) / NOM_FICHIER)

    res, journal = simuler(prix, poids)

    print("\nRebalancements :")
    print(journal.to_string(formatters={"Turnover": "{:.1%}".format,
                                        "Frais (EUR)": "{:,.0f}".format,
                                        "Cash résiduel": "{:.3%}".format}))
    print("\nQualité de la réplication :")
    for nom, valeur in mesures(res).items():
        print(f"  {nom:<30} {valeur:+.2%}")
    tracer(res, poids)


if __name__ == "__main__":
    main()
