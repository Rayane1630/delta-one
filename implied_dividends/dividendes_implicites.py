"""
DIVIDENDES IMPLICITES PAR LA PARITÉ CALL-PUT
============================================

Objectif
--------
Extraire des prix d'options européennes (ex. options sur l'Euro Stoxx 50)
la courbe des dividendes anticipés par le marché, année par année,
et la comparer aux futures sur dividendes.

Principe
--------
Parité call-put pour une option européenne de maturité T et de strike K :

        C(K) - P(K) = DF x (F - K)

    C, P : prix du call et du put
    DF   : facteur d'actualisation jusqu'à T
    F    : prix forward du sous-jacent pour T

Pour une maturité donnée, C - P est une DROITE en fonction du strike :
    - pente               = -DF
    - ordonnée à l'origine =  DF x F

Une régression linéaire sur plusieurs strikes donne donc DF et F
directement à partir des prix d'options, sans courbe de taux.

Le forward s'écrit aussi : F = (S - VA(Div)) x exp(-repo x T) / DF
d'où la valeur actuelle des dividendes jusqu'à T :

        VA(Div) = S - (DF x F) x exp(repo x T)

Avec repo = 0, le dividende obtenu est un dividende "net de repo".


FICHIER EXCEL À CRÉER POUR UTILISER LE CODE
-------------------------------------------
Nom du fichier : donnees_dividendes_implicites.xlsx
Emplacement    : le dossier indiqué dans la variable DOSSIER_DONNEES ci-dessous

Onglet "Parametres"  (valeurs en colonne B)
    B2 : sous-jacent            (ex. SX5E Index)
    B3 : date de valorisation   (format date, ex. 28/10/2026)
    B4 : spot de clôture        (ex. 5500,00)
    B5 : taux de repo annuel    (ex. 0,002 pour 0,2 %, mettre 0 si inconnu)

Onglet "Options"  (en-têtes en ligne 1, données à partir de la ligne 2)
    Colonne A : Maturite   (date d'échéance de l'option)
    Colonne B : Strike
    Colonne C : Prix_Call  (prix mid)
    Colonne D : Prix_Put   (prix mid, même strike et même maturité que le call)

Onglet "Dividend_Futures"  (OPTIONNEL, en-têtes en ligne 1, données à partir de la ligne 2)
    Colonne A : Annee        (ex. 2027)
    Colonne B : Prix_Future  (prix du future sur dividende, en points d'indice)

Règles à respecter :
    - options EUROPÉENNES uniquement (une option américaine casse la parité) ;
    - au moins 5 strikes par maturité, autour de la monnaie (90 % à 110 % du spot) ;
    - maturités de décembre, pour coller aux futures sur dividendes annuels ;
    - tous les prix relevés au même moment (clôture).

Lancement
---------
    python dividendes_implicites.py          -> lit le fichier Excel
    python dividendes_implicites.py --demo   -> tourne sur des données fictives
"""

import sys
from datetime import date, datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import norm


# ---------------------------------------------------------------------------
# PARAMÈTRES À MODIFIER
# ---------------------------------------------------------------------------

# Dossier où se trouve le fichier Excel : remplacer les XXXX par ton chemin
# ex. r"C:\Users\Rayane\Documents\Projets\Dividendes"
DOSSIER_DONNEES = r"XXXXXXXXXXXXXXXXXXXXXXXX"
NOM_FICHIER = "donnees_dividendes_implicites.xlsx"

# Nombre minimum de strikes pour faire une régression fiable
NB_STRIKES_MIN = 5

# Convention de calcul du temps : nombre de jours / 365
BASE_JOURS = 365.0


# ---------------------------------------------------------------------------
# 1. LECTURE DES DONNÉES
# ---------------------------------------------------------------------------

def lire_donnees(chemin_fichier):
    """Lit le fichier Excel et renvoie les paramètres, les options et les futures."""
    chemin = Path(chemin_fichier)
    if not chemin.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : {chemin}\n"
            "Vérifie DOSSIER_DONNEES en haut du script, ou lance avec --demo."
        )

    # Paramètres : on lit la colonne B, lignes 2 à 5
    feuille_param = pd.read_excel(chemin, sheet_name="Parametres", header=None)
    parametres = {
        "sous_jacent": str(feuille_param.iloc[1, 1]),
        "date_valo": pd.to_datetime(feuille_param.iloc[2, 1]).date(),
        "spot": float(feuille_param.iloc[3, 1]),
        "repo": float(feuille_param.iloc[4, 1] or 0.0),
    }

    # Options : 4 colonnes, en-têtes en ligne 1
    options = pd.read_excel(chemin, sheet_name="Options", usecols="A:D")
    options.columns = ["Maturite", "Strike", "Prix_Call", "Prix_Put"]
    options = options.dropna()
    options["Maturite"] = pd.to_datetime(options["Maturite"]).dt.date

    # Futures sur dividendes : onglet optionnel
    try:
        futures = pd.read_excel(chemin, sheet_name="Dividend_Futures", usecols="A:B")
        futures.columns = ["Annee", "Prix_Future"]
        futures = futures.dropna()
        futures["Annee"] = futures["Annee"].astype(int)
    except ValueError:
        futures = pd.DataFrame(columns=["Annee", "Prix_Future"])

    return parametres, options, futures


# ---------------------------------------------------------------------------
# 2. RÉGRESSION DE LA PARITÉ CALL-PUT, MATURITÉ PAR MATURITÉ
# ---------------------------------------------------------------------------

def regression_parite(options, parametres):
    """
    Pour chaque maturité : régression de (C - P) sur K.
    Renvoie un tableau avec DF, forward, taux implicite et dividendes cumulés.
    """
    spot = parametres["spot"]
    repo = parametres["repo"]
    date_valo = parametres["date_valo"]

    resultats = []
    for maturite, groupe in options.groupby("Maturite"):
        if len(groupe) < NB_STRIKES_MIN:
            print(f"  {maturite} ignorée : seulement {len(groupe)} strikes.")
            continue

        T = (maturite - date_valo).days / BASE_JOURS
        if T <= 0:
            continue

        strikes = groupe["Strike"].to_numpy(dtype=float)
        c_moins_p = (groupe["Prix_Call"] - groupe["Prix_Put"]).to_numpy(dtype=float)

        # Droite C - P = a + b x K   (polyfit renvoie d'abord la pente)
        pente, ordonnee = np.polyfit(strikes, c_moins_p, 1)

        df = -pente                     # facteur d'actualisation implicite
        forward = ordonnee / df         # forward implicite
        taux = -np.log(df) / T          # taux zéro-coupon implicite

        # Qualité de la régression (R²) : doit être très proche de 1
        prevision = ordonnee + pente * strikes
        r2 = 1 - np.sum((c_moins_p - prevision) ** 2) / np.sum((c_moins_p - c_moins_p.mean()) ** 2)

        # Valeur actuelle des dividendes versés entre aujourd'hui et T
        va_div_cumul = spot - ordonnee * np.exp(repo * T)

        resultats.append({
            "Maturite": maturite,
            "T": T,
            "DF": df,
            "Taux_implicite": taux,
            "Forward": forward,
            "VA_Div_cumul": va_div_cumul,
            "R2": r2,
            "Nb_strikes": len(groupe),
        })

    return pd.DataFrame(resultats).sort_values("T").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. PASSAGE AUX DIVIDENDES ANNUELS
# ---------------------------------------------------------------------------

def dividendes_annuels(courbe):
    """
    Dividende de chaque période = VA cumulée(T_i) - VA cumulée(T_i-1),
    capitalisé jusqu'à T_i (division par DF) pour être comparable
    au prix d'un future sur dividende, qui n'est pas actualisé.
    Hypothèse simplificatrice : dividendes payés à la maturité de la période.
    """
    courbe = courbe.copy()
    va_periode = courbe["VA_Div_cumul"].diff()
    va_periode.iloc[0] = courbe["VA_Div_cumul"].iloc[0]

    courbe["Div_periode"] = va_periode / courbe["DF"]
    courbe["Annee"] = [m.year for m in courbe["Maturite"]]
    return courbe


# ---------------------------------------------------------------------------
# 4. GRAPHIQUE
# ---------------------------------------------------------------------------

def tracer_courbe(courbe, futures, parametres):
    """Barres = dividendes implicites ; points = futures sur dividendes."""
    fig, ax = plt.subplots(figsize=(10, 5.5))

    ax.bar(courbe["Annee"].astype(str), courbe["Div_periode"],
           color="#1F3864", alpha=0.85, label="Dividende implicite (parité call-put)")

    for x, y in zip(courbe["Annee"].astype(str), courbe["Div_periode"]):
        ax.annotate(f"{y:.1f}", (x, y), textcoords="offset points",
                    xytext=(0, 4), ha="center", fontsize=9)

    if not futures.empty:
        fut = futures[futures["Annee"].isin(courbe["Annee"])]
        ax.plot(fut["Annee"].astype(str), fut["Prix_Future"], "o",
                color="#C00000", markersize=8, label="Future sur dividende")

    ax.set_title(f"Dividendes implicites {parametres['sous_jacent']} "
                 f"au {parametres['date_valo']:%d/%m/%Y}")
    ax.set_xlabel("Année")
    ax.set_ylabel("Dividende (points d'indice)")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    fig.tight_layout()

    sortie = Path(__file__).with_name("courbe_dividendes_implicites.png")
    fig.savefig(sortie, dpi=150)
    print(f"\nGraphique enregistré : {sortie}")
    plt.show()


# ---------------------------------------------------------------------------
# 5. DONNÉES FICTIVES (mode --demo)
# ---------------------------------------------------------------------------

def troisieme_vendredi(annee, mois):
    """Date d'échéance standard des options sur indice : 3e vendredi du mois."""
    premier = date(annee, mois, 1)
    decalage = (4 - premier.weekday()) % 7
    return date(annee, mois, 1 + decalage + 14)


def prix_black(forward, strike, T, df, vol):
    """Prix Black (sur forward) d'un call et d'un put européens."""
    d1 = (np.log(forward / strike) + 0.5 * vol ** 2 * T) / (vol * np.sqrt(T))
    d2 = d1 - vol * np.sqrt(T)
    call = df * (forward * norm.cdf(d1) - strike * norm.cdf(d2))
    put = df * (strike * norm.cdf(-d2) - forward * norm.cdf(-d1))
    return call, put


def generer_donnees_fictives():
    """
    Crée un jeu de prix d'options cohérent avec des dividendes connus,
    pour tester que le code retrouve bien ces dividendes.
    """
    rng = np.random.default_rng(42)
    date_valo = date(2026, 10, 28)
    spot, taux, vol = 5500.0, 0.022, 0.18

    # Dividendes "vrais" par année (points d'indice), payés en milieu de période
    vrais_div = {2026: 12.0, 2027: 168.0, 2028: 175.0, 2029: 181.0, 2030: 186.0, 2031: 190.0}

    lignes, futures = [], []
    for annee, div in vrais_div.items():
        maturite = troisieme_vendredi(annee, 12)
        T = (maturite - date_valo).days / BASE_JOURS
        df = np.exp(-taux * T)

        # VA des dividendes cumulés jusqu'à cette maturité
        va_div = 0.0
        for a, d in vrais_div.items():
            if a > annee:
                break
            fin = (troisieme_vendredi(a, 12) - date_valo).days / BASE_JOURS
            debut = max(0.0, (troisieme_vendredi(a - 1, 12) - date_valo).days / BASE_JOURS)
            va_div += d * np.exp(-taux * 0.5 * (debut + fin))

        forward = (spot - va_div) / df
        for k in np.arange(0.90, 1.105, 0.025) * spot:
            call, put = prix_black(forward, k, T, df, vol)
            bruit = rng.normal(0, 0.15, 2)          # petit bruit de bid/ask
            lignes.append([maturite, round(k), call + bruit[0], put + bruit[1]])

        if annee > 2026:
            futures.append([annee, div + rng.normal(0, 1.5)])

    parametres = {"sous_jacent": "INDICE FICTIF", "date_valo": date_valo,
                  "spot": spot, "repo": 0.0}
    options = pd.DataFrame(lignes, columns=["Maturite", "Strike", "Prix_Call", "Prix_Put"])
    futures = pd.DataFrame(futures, columns=["Annee", "Prix_Future"])
    return parametres, options, futures


# ---------------------------------------------------------------------------
# PROGRAMME PRINCIPAL
# ---------------------------------------------------------------------------

def main():
    if "--demo" in sys.argv:
        print("Mode démo : données fictives.")
        parametres, options, futures = generer_donnees_fictives()
    else:
        chemin = Path(DOSSIER_DONNEES) / NOM_FICHIER
        print(f"Lecture de {chemin}")
        parametres, options, futures = lire_donnees(chemin)

    courbe = regression_parite(options, parametres)
    if courbe.empty:
        print("Aucune maturité exploitable : vérifie le fichier.")
        return
    courbe = dividendes_annuels(courbe)

    # Affichage du tableau de résultats
    affichage = courbe[["Maturite", "T", "DF", "Taux_implicite", "Forward",
                        "VA_Div_cumul", "Div_periode", "R2"]].copy()
    affichage["Taux_implicite"] = (affichage["Taux_implicite"] * 100).map("{:.2f} %".format)
    print("\nRésultats par maturité :")
    print(affichage.round(4).to_string(index=False))

    tracer_courbe(courbe, futures, parametres)


if __name__ == "__main__":
    main()
