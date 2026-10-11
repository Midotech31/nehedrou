# Audio Nehedrou — intégration et qualification

L’audio est une aide à la pratique accompagnée. L’orthophoniste choisit les mots et les objectifs ; l’application ne juge pas la production de parole et ne produit pas de diagnostic.

## Créer un modèle dans le CMS

1. Enregistrer le brouillon de l’activité avec sa variété et les deux mots/prompts. Depuis « Mots et médias », ouvrir l’import éditorial.
2. Choisir **Audio**, la variété exacte, le texte réellement prononcé, l’origine humaine ou synthétique et, pour la darja, les précisions régionales utiles. Le formulaire ne demande pas l’identité civile du locuteur.
3. Importer un WAV/MP3 ou enregistrer une voix **adulte autorisée**. Le microphone ne s’ouvre qu’après l’action explicite de l’utilisateur, une confirmation adulte et l’autorisation du navigateur. La capture dure au maximum 45 secondes. Changer d’onglet, annuler ou quitter ferme la capture.
4. Écouter l’aperçu local, puis « Utiliser cet enregistrement ». Le navigateur convertit la capture en WAV PCM16 mono. Si l’affectation du fichier n’est pas prise en charge, télécharger le WAV et l’importer. Aucun envoi avant la sauvegarde du formulaire. Conserver une copie locale en cas de coupure ou de quota de stockage.
5. Documenter droits, usages et consentement ; déposer la preuve dans « Contenus et droits ». La case de capture ne crée aucune preuve documentaire et ne vaut pas licence commerciale.
6. Sauvegarder le média, revenir au brouillon et sélectionner l’audio du mot correspondant. Le CMS refuse un silence détecté ou une association de texte/variété différente lorsqu’elle est documentée. Le sélecteur présente le texte et la variété, la date et un identifiant court.
7. Soumettre la version aux relectures linguistique et clinique existantes. Modifier l’audio d’un contenu publié exige une nouvelle version. Les droits, les fichiers et les décisions restent liés à leurs empreintes.

L’interface existe en français, anglais et arabe avec RTL. Pitou garde les droits de création de brouillons dans les quatre variétés ; ses permissions de publication ne sont pas élargies. Ne jamais enregistrer un enfant ou un patient dans cet outil éditorial.

## Écouter

Le même lecteur est présent dans la bibliothèque, les activités à domicile, l’aperçu éditorial et les sondes professionnelles : contrôles natifs, réécoute, vitesse originale/0,85×, indication de source, durée et erreurs récupérables. Les fichiers privés utilisent des routes authentifiées ; les sondes conservent leur périmètre professionnel et leurs captures de version. HEAD et les demandes Range passent les mêmes vérifications que GET. Le serveur vérifie les octets avant de les livrer, répond 206 pour une plage simple et 416 pour une plage insatisfaisable.

Une seule piste est lue à la fois. Une étape suivante, un arrêt de l’activité, la soumission, un changement d’onglet ou une sortie suspend l’écoute. Il n’y a pas de lecture automatique. L’import et les contrôles audio natifs restent disponibles sans JavaScript.

Le ralentissement est une aide à l’écoute et modifie les durées acoustiques. Pour examiner les sons, employer le fichier à vitesse originale ; aucun traitement ne certifie une prononciation correcte.

## Qualité et limites

Les WAV sont mesurés pour repérer le silence, le niveau très faible et une saturation possible. Ces indicateurs ne mesurent ni l’intelligibilité, ni le bruit de fond à partir d’un seul niveau, ni la justesse phonétique. Les MP3 sont contrôlés structurellement et doivent être écoutés ; ils n’ont pas d’analyse de niveau PCM dans cette version. Formats admis : WAV PCM/MP3, durée 0,05–60 s, 8–96 kHz, mono/stéréo, 15 Mio maximum. Les audios silencieux et les nouvelles sources déclarées indéterminées ne satisfont pas la qualification documentaire clinique.

Les fichiers anciens ne sont pas modifiés ni rétroactivement approuvés. Un média sans origine vocale renseignée affiche « Origine de la voix non documentée ». Le statut affiché de voix adulte décrit la provenance, pas une approbation clinique. Les décisions humaines restent dans les relectures de la version.

Une synthèse **de l’appareil**, si une voix correspondante est disponible, peut aider les démonstrations lexicales FR/EN/arabe standard. Elle est explicitement non relue, exclue des paires/contrastes phonologiques et de la darja. Aucun audio d’arabe standard n’est présenté comme darja. L’absence de voix ou de fichier conduit aux consignes de l’accompagnant. Aucune voix humaine native ni aucune efficacité clinique n’est inventée.

La recette privée utilise une phrase synthétique anglaise non silencieuse pour vérifier import, stockage, décodage et lecture ; elle n’est pas diffusée comme contenu thérapeutique. Les fixtures tonales des tests unitaires ne sont pas des modèles de parole.

## Sources vérifiées le 11 octobre 2026

- [ASHA — Speech Sound Disorders](https://www.asha.org/practice-portal/clinical-topics/articulation-and-phonology/) : approches, perception et adaptation aux systèmes phonologiques. Cette référence étaye la prudence sur les modèles ; elle ne valide pas Nehedrou.
- [ASHA — Multilingual Service Delivery](https://www.asha.org/practice-portal/professional-issues/multilingual-service-delivery/) : distinguer variété/accent et trouble ; tenir compte du répertoire linguistique.
- [MDN — getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia) : contexte sécurisé et permission utilisateur obligatoire.
- [MDN — MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder) : capture et formats dépendants du navigateur. Le décodage/conversion WAV doit rester vérifié sur les navigateurs cibles.
- [MDN — Range](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Range) : demandes partielles et réponses HTTP.
- [MDN — getVoices](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis/getVoices) : les voix disponibles dépendent de l’appareil.

L’intégration utilise les outils du navigateur et le stockage privé déjà provisionné. Aucun service vocal payant ni nouvelle souscription n’a été ajouté. La relecture et la constitution d’un corpus humain local restent nécessaires avant de revendiquer des modèles de prononciation approuvés, notamment en darja.
