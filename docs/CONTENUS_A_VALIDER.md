> Archive éditoriale du 10 octobre 2026 : les chiffres de corpus ci-dessous décrivent cette livraison. Pour l'état courant, voir [l'inventaire horodaté](INVENTAIRE_CONTENUS.md) et `manage.py content_inventory --json`.

# Contenus à valider — corpus v2

Mise à jour du 10 octobre 2026. Source active : catalog-candidates.json, **37 fiches candidates v2 : 19 FR, 17 EN, 1 darja**. Aucune approbation clinique ou linguistique n’est fournie, aucun audio clinique validé n’est livré. Les transcriptions FR/EN sont des propositions de travail à relire ; la fiche darja laisse volontairement les transcriptions vides.

## Ce qui est réellement préparé

Chaque fiche contient les mots et illustrations, un contraste proposé, des consignes françaises/anglaises/arabes, un guide structuré (objectif, public, découverte, écoute/choix, échange, aides, limites et notes linguistiques) et des références indiquant explicitement ce qu’elles soutiennent. Une référence d’approche ne valide jamais la paire, l’enfant concerné ou Nehedrou.

L’arabe des instructions est une langue de communication écrite. Il ne constitue pas une transcription de la darja ni un modèle de parole dialectale.

## Propositions écartées du corpus actif

catalog-candidates-v1.json archive les 60 propositions initiales. catalog-exclusions-v2.json documente **23 mises en attente**, sans supprimer les données historiques : pot/peau est homophone ; mouse/mouth et sun/bun utilisent des images inexactes ; log/dog peut comporter une différence vocalique selon la variété américaine ; 19 propositions arabes ne disposent pas d’une analyse locale suffisante. Leur présence dans une archive n’est pas une recommandation de les employer.

La seule proposition darja active est دار / نار (maison / feu). Souag (2005), Notes on the Algerian Arabic Dialect of Dellys, atteste daṛ et naṛ, p. 155 et 164. Cela documente des formes locales et justifie une hypothèse de contraste initial ; cela ne fournit ni norme nationale, ni validation pédiatrique, ni IPA/audio approuvé. Voir [l’article primaire](https://journals.uco.es/index.php/edna/article/view/8669/8173).

## Revue de chaque version avant publication clinique

1. Confirmer la variété précise et les usages de la famille, les sens et la familiarité des mots, la reconnaissance des images et leurs droits.
2. Confirmer l’analyse phonologique réelle : nombre et position des différences, réalisation des voyelles/rhotiques et lien avec la cible choisie après évaluation. Ne pas déduire un traitement d’une différence orthographique.
3. Relire objectif, public, consignes, aides et limites ; vérifier que la famille comprend la tâche. Le praticien adapte la sélection, le rythme et l’accompagnement.
4. Produire deux modèles vocaux adultes autorisés, les contrôler pour prononciation, variété, qualité et diffusion. Aucun enregistrement d’enfant. Aucun audio généré n’est réputé clinique du seul fait qu’il est lisible.
5. Obtenir les décisions clinique et linguistique sur l’empreinte exacte de la fiche et des médias, avec des relecteurs compétents pour cette variété. Les permissions logicielles ne prouvent pas leur compétence.

## Conservation et mise en service des démos

seed_candidates crée les versions v2 sans remplacer une fiche ou une revue existante. Avec --demo-copies et DEMO_MODE, il crée des copies explicitement non validées ; il ne crée aucune approbation. Les versions v1 publiées et leurs rapports restent inchangés. current_catalog filtre les anciennes démos connues pour la découverte et les nouvelles affectations, sans les effacer de l’historique. Le catalogue et les exemples publics se fondent sur le corpus actif, pas sur l’archive.

La migration 0006 ajoute deux champs vides. fingerprint omet ces nouveaux champs lorsqu’ils sont vides : les empreintes historiques restent identiques. Un guide ou une référence renseignés font partie de l’empreinte et rendent nécessaire une nouvelle relecture. Aucune correspondance de revue ou décision positive n’est fabriquée.
