# NX2Apple « cartouche » : guide

Cette branche (`cartouche`) est un fork personnel de [NX2Apple](https://github.com/LNPANDY/NX2Apple). Elle garde tout le moteur
(nxnative : le code du jeu tourne nativement sur l'iPhone, ce n'est pas un émulateur) et ajoute :

- **Sur l'iPhone** : une bibliothèque en boîtiers. En paysage, un carrousel de jaquettes verticales sur l'illustration du jeu,
  avec des points de pagination. Toucher un jeu (ou A à la manette) ouvre sa boîte : le couvercle pivote, le mode d'emploi est
  à gauche, la cartouche à droite. **Insérer la cartouche** (A) la soulève, l'amène à la fente, elle s'enfonce avec un clic
  sonore et une vibration, puis le jeu démarre. En haut : temps de jeu, dernière partie et nombre de lancements.
  B ou **Retour** referme la boîte, X ou **Infos du jeu** ouvre les réglages du jeu.
- **Sur le PC Windows** : le lanceur NX2Apple habituel, avec deux ajouts. Clic droit sur un jeu de la bibliothèque,
  **Choisir la jaquette du boîtier…**, et le bouton **Publier sur GitHub**, qui envoie `NX2Apple.ipa` dans une release
  de votre dépôt **privé**, prête pour FlareStore.

Rien n'est envoyé à GitHub à part l'IPA, et seulement vers un dépôt privé : vos dumps, vos clés et les données des jeux
restent sur votre PC.

## 1. Une seule fois : le fork et sa compilation

1. Dans **Settings → General** du fork, mettez la branche par défaut sur `cartouche`.
2. Dans l'onglet **Actions** du fork, activez les workflows (GitHub les désactive sur un fork).
3. Lancez **Actions → Build the cartridge launcher → Run workflow** (un push sur `cartouche` le lance aussi).
   Le premier job compile la coque iPhone sur un Mac de GitHub (Xcode 27.2), le second fabrique le lanceur Windows.
   Comptez 30 à 45 minutes. C'est gratuit tant que le fork est public (il ne contient aucun jeu).
4. Dans **Releases**, téléchargez `NX2Apple-windows-x64.zip`, décompressez-le, lancez `NX2Apple.exe`.
   Le lanceur se met ensuite à jour depuis les releases de ce fork, jamais depuis celles de NX2Apple.

## 2. Sur le PC : préparer et compiler un jeu

1. Dans les **Réglages** du lanceur, liste des dépendances : **Installer tout ce qui manque** (.NET 10, LLVM-MinGW, SDK iPhoneOS).
   Les **Metal Developer Tools for Windows** se téléchargent à la main sur
   <https://developer.apple.com/download/all/?q=metal%20developer%20tools> (identifiant Apple gratuit).
2. Choisissez le dossier du jeu (jeu de base, mise à jour, DLC) et votre `prod.keys`, cible **iPhone / iPad**,
   **Contenu de l’IPA : App partagée**, puis **Lancer la compilation**.
3. Clic droit sur le jeu dans la bibliothèque → **Choisir la jaquette du boîtier…** : une image verticale
   (le recto du boîtier, environ 0,62 de large pour 1 de haut). Sans jaquette, le boîtier montre l'illustration du jeu
   recadrée avec son titre.
4. **Publier sur GitHub** : le lanceur demande le dépôt (par défaut `nx2apple-ipa` sous votre compte, créé en privé
   s'il n'existe pas), refait l'IPA si une jaquette a changé, puis l'envoie. La connexion vient de GitHub CLI
   (`gh auth login`) ou de la variable `GITHUB_TOKEN`. Un dépôt public est refusé : l'IPA contient le code de vos jeux.

## 3. Sur l'iPhone

1. Dans Safari, connecté à GitHub, ouvrez
   `https://github.com/<vous>/nx2apple-ipa/releases/latest/download/NX2Apple.ipa` (le lanceur affiche ce lien).
2. Ouvrez l'IPA dans **FlareStore**, signez et installez.
3. **Données des jeux** : chaque jeu a besoin de son `romfs.img`. Le lanceur le produit avec la compilation
   (carte **Installation**, étape **Envoyer les données du jeu**). Copiez-les dans un dossier de l'app Fichiers (iCloud Drive, Sur mon iPhone ou une clé USB-C),
   puis dans l'app : **Réglages → Données du jeu**, choisissez ce dossier une fois. Les fichiers sont reconnus par leur
   contenu, les noms de dossiers n'ont pas d'importance. Autre voie : par câble avec l'app **Appareils Apple** de Windows,
   dans les fichiers de l'app, sous `games/<title ID>/`.

## Limites à connaître

- **Seuls les jeux qui ont un profil** dans nxnative démarrent (147 aujourd'hui, liste dans [GAMES.md](GAMES.md)).
  La version de la mise à jour doit correspondre à celle du profil.
- **La compilation sous Windows reste expérimentale** chez NX2Apple. Les jeux dont les shaders sont dans la RomFS
  (Mario Odyssey, Mario Kart 8 Deluxe, les Zelda, Metroid Dread…) sont ceux qui passent. Les jeux qui ont besoin
  d'exécuter leur propre code pendant la compilation (capture de shaders, Oodle, Unreal) sont refusés sous Windows.
- **Mémoire** : les gros jeux (Tears of the Kingdom) ont besoin de l'entitlement *Increased Memory Limit*. L'IPA le
  demande. Il n'est conservé que si le profil de provisionnement de votre certificat FlareStore l'autorise. Sinon iOS
  limite l'app à environ 3,4 Go et ces jeux se ferment au chargement.
- iOS ou iPadOS 26 ou plus récent.

## Suivre NX2Apple

Les nouveaux profils de jeux et les corrections du moteur arrivent sur `main` chez NX2Apple. Pour les récupérer :

```bash
git remote add upstream https://github.com/LNPANDY/NX2Apple.git   # une seule fois
git fetch upstream
git merge upstream/main
python tools/l10n_shell_catalogs.py                               # régénère les textes de l'app iPhone
git push origin cartouche                                         # relance la compilation
```

## Ce que change cette branche

| Où | Quoi |
|---|---|
| `frontend-ios/Sources/ShellUI/Cartridge/` | boîtier, cartouche, boîte ouverte, sons synthétisés (aucun fichier audio) |
| `frontend-ios/Sources/ShellUI/LibraryView+Cartridge.swift` | ouverture de la boîte à la place du lancement direct, A, B et X |
| `frontend-ios/Sources/ShellUI/CoverFlowView.swift` | jaquettes verticales, points de pagination, fond moins flouté |
| `frontend-ios/Sources/ShellHost/PlayStats.swift` | temps de jeu et nombre de lancements |
| `frontend-qt/nspb_qt/covers.py`, `github_publish.py` | jaquettes et publication sur GitHub |
| `frontend/l10n/*.json` | les nouveaux textes, dans les 10 langues pour l'iPhone |
| `.github/workflows/cartouche-launcher.yml` | compilation de la coque (macOS) et du lanceur (Windows), release du fork |
