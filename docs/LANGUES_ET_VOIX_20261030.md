# Langue des contenus et voix de démonstration — 30 octobre 2026

Les menus et titres traduits suivent la langue d’interface. Les consignes et chaque section du guide suivent exclusivement `user.instruction_language`, sans substitution automatique d’une autre langue. `guide_language` renvoie une copie de présentation portant `language` ; aucune clé n’est ajoutée aux guides enregistrés.

| Contenu | Déclaration utilisée |
|---|---|
| Mots français du pilote | `lang="fr-FR"`, direction LTR |
| Mots anglais du pilote | `lang="en-US"`, direction LTR |
| Mots arabes standard | `lang="ar"`, direction RTL |
| Mots de la proposition darja algérienne | `lang="ar-DZ"`, direction RTL ; aucune norme nationale déduite |
| API et phonèmes | `lang="und-fonipa"`, `dir="ltr"` |
| Langue non documentée | `lang="und"` |

Les alternatives des images et les légendes des mots portent la langue de la variété. Les contrôles et messages audio conservent leur propre langue d’interface, y compris à l’intérieur d’un groupe d’images portant la langue des mots. Les notes libres sans langue enregistrée ne sont pas attribuées automatiquement à la préférence actuelle de leur auteur.

Les références acceptent des métadonnées facultatives `scope_language` et `title_language`, sous forme d’étiquettes de langue explicites. Leur valeur est conservée lorsque le texte correspondant n’a pas changé dans le formulaire éditorial. Un texte modifié sans nouvelle déclaration redevient de langue non documentée. Les textes et empreintes des références existantes ne sont pas réécrits pour leur ajouter une langue.

Le registre `source-language-declarations-20261030.json` identifie les explications françaises effectivement présentes dans les sources arabes livrées, par correspondance exacte du lien et du texte. Une explication différente ou inconnue reste `und` ; les titres bibliographiques sans métadonnée explicite restent également `und`. Aucune détection linguistique approximative n’est utilisée.

La voix synthétique reste limitée aux démonstrations lexicales autorisées. La darja, les paires de mots phonologiques, les contrastes phonologiques et les activités réelles restent exclus côté serveur et dans le contrôleur JavaScript. La préférence porte d’abord sur l’étiquette complète demandée ; à défaut, une voix de la même langue peut être sélectionnée. Le code réellement sélectionné, par exemple `en-GB` pour une demande `en-US`, est affiché et transmis à l’énoncé. Un accent régional différent est explicitement indiqué. Une voix sans région déclarée conserve sa propre étiquette, sans lui inventer un accent. Aucune voix clinique relue n’est créée.

Les régressions couvrent une interface arabe avec consignes françaises et mots anglais, puis une interface française avec consignes arabes et mots darja, sur les vues détail, impression et pratique. Elles vérifient les langues effectives du DOM, les alternatives des images et la direction de l’API. Un test Node exécute le vrai contrôleur de voix avec des voix simulées pour vérifier la sélection exacte, la substitution régionale affichée et les exclusions. Cela ne constitue pas un essai acoustique sur téléphone ni une certification de lecteur d’écran.
