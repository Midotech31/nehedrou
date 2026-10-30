# Glossaire éditorial phonologique — préparation du 30 octobre 2026

Les équivalents ci-dessous harmonisent les libellés techniques du CMS. Ils restent à relire par un orthophoniste et un locuteur compétent ; aucune approbation humaine n’est attribuée. Les phonèmes, indices, graphies et transcriptions stockés restent inchangés.

| Notion | Français | English | العربية | Portée dans le CMS |
|---|---|---|---|---|
| phoneme | phonème | phoneme | فونيم، وحدة صوتية مميّزة | Une entrée de la liste explicite ; plusieurs caractères IPA peuvent représenter un seul phonème. |
| phonemic segment | unité phonémique | phonemic segment | وحدة فونيمية | Dans ces listes, le segment désigne une unité phonémique documentée, sans découpage automatique des caractères IPA. |
| syllable | syllabe | syllable | مقطع لفظي | Notion distincte, non représentée par la liste des phonèmes. Ne pas traduire cette liste par « المقاطع الصوتية ». |
| target occurrence | occurrence cible | target occurrence | موضع الفونيم المستهدف | Renvoie à un indice explicite et à une position ; l’indexation dépend du formulaire et reste affichée telle quelle. |
| IPA transcription | transcription API | IPA transcription | نسخ بالأبجدية الصوتية الدولية | Analyse proposée, à vérifier dans la variété orale visée ; sa présence ne donne pas une approbation clinique. |

L’affriquée proposée `/dʒ/` ou une voyelle longue telle que `/iː/` peut occuper une seule entrée de la liste explicite de ces fiches. Cela ne transforme ni les caractères ni les positions enregistrées et ne fixe aucune norme orale pour tous les locuteurs. Le sens clinique et la segmentation demandent une relecture compétente.

Neuf valeurs existantes du catalogue arabe ont été harmonisées autour de « فونيم ». La consigne arabe d’écoute des dix contrastes MSA emploie désormais « التقسيم إلى فونيمات ». Les fichiers `.mo` sont régénérés par la vérification générale de livraison.

## Matrice de parité et application aux versions existantes

La [matrice des dix contrastes](msa-editorial-parity-20261030.json) répertorie, pour chaque série et chaque langue, les précautions propres à la paire, les formes isolées, l’accompagnement et la familiarité. Chaque décision humaine est explicitement en attente. Les textes préparés ne sont pas une revue clinique ou linguistique.

Les dix séries sont dans `docs/arabic-library-v1.json`. Le catalogue de base `docs/catalog-candidates.json` comporte 37 autres candidats et aucune de ces dix séries ; il ne doit pas recevoir de doublons. Les anciens imports restent préservés par `seed_arabic_library`.

Pour une installation existante, `python manage.py prepare_msa_guide_revisions --actor NOM_UTILISATEUR` prépare uniquement un compte rendu sans écrire de version. L’option explicite `--apply` crée de nouvelles versions **en brouillon**, seulement si les anciens guides et les éléments linguistiques correspondent à la référence conservée dans la matrice et si l’acteur dispose du droit éditorial d’édition sur la variété. Elle ne remplace aucun ancien guide, avis, programme ou instantané et ne crée aucune approbation ni décision de disponibilité. Les séries déjà à jour sont ignorées ; un travail éditorial différent est signalé pour traitement humain. Aucune de ces commandes n’a été exécutée sur la base publiée dans cette correction.
