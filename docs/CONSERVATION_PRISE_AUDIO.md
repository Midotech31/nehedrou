# Conservation d’une prise adulte dans l’onglet

Cette amélioration concerne seulement un WAV créé par l’enregistreur puis joint
explicitement avec « Use this recording ». La prise reste en mémoire dans cet
onglet : aucun stockage navigateur persistant, aucune voix d’enfant, aucun envoi
avant la sauvegarde explicite. Le sélecteur de fichiers et le parcours sans
JavaScript conservent leur soumission HTML habituelle.

Une erreur de validation ou de stockage laisse le WAV et son aperçu disponibles.
La correction après un refus 422 conserve la clé de tentative : aucun reçu n’a
été enregistré. Une nouvelle prise réinitialise cette clé. Une réponse perdue ne
déclenche aucune nouvelle tentative automatique ; l’utilisateur peut réessayer
le même contenu explicitement. Le serveur retrouve alors son reçu et son média.
L’attente du navigateur est bornée à 60 secondes, lecture de la réponse comprise.
Au-delà, les commandes se réactivent et le WAV reste disponible. L’arrêt de la
requête côté navigateur ne prouve pas un arrêt du serveur : la même clé est donc
conservée pour une nouvelle tentative explicite, sans renvoi automatique.
Si le contenu diffère d’un envoi déjà terminé, il répond 409 sans nouveau média.
Une collision avec le reçu d’un autre compte n’en révèle ni l’URL ni le média.
Un reçu dont le fichier est absent, altéré ou révoqué ne confirme pas une nouvelle
sauvegarde et ne provoque aucun remplacement : la prise locale reste disponible.

La migration `catalog.0016_mediauploadreceipt` ajoute un reçu technique privé,
immuable et lié à l’acteur, au SHA exact des champs/fichier, au média et au
contexte guidé original. La page GET du résultat appartient à l’acteur ; elle ne
crée aucune liaison, licence, validation ou approbation. Le contexte original
conserve son expiration et son empreinte. La liaison à un mot reste un POST
distinct soumis aux vérifications existantes.

La sauvegarde verrouille d’abord le compte puis son droit d’édition exact. Le
retrait d’un droit utilise déjà le verrou de cette même ligne : un retrait acquis
d’abord fait refuser l’envoi ; une sauvegarde acquise d’abord peut terminer son
écriture privée avant le retrait. Celui-ci n’annule pas rétroactivement un média.
Ce contrat n’accorde aucune disponibilité clinique.

Média, reçu et journal sont écrits dans la même transaction SQL. Avant que le
corps de cette transaction soit terminé, un échec nettoie au mieux uniquement les
nouveaux noms réellement écrits dans le stockage. Une fois le journal écrit,
COMMIT peut avoir été envoyé : une erreur d’acquittement ne déclenche donc aucun
nettoyage. Le navigateur reçoit un état incertain ; le réessai identique retrouve
le reçu éventuellement validé sans supprimer le WAV. Il ne supprime jamais une
prise précédente ou rejouée. Le stockage de fichiers n’est pas une
transaction SQL ; une panne du stockage pendant ce nettoyage peut laisser un
objet orphelin à traiter par l’exploitation. Aucun nettoyage automatique de
prises existantes n’est introduit. La suppression autorisée d’un média supprime
aussi son reçu ; les reçus ne créent pas un obstacle supplémentaire à la purge.

`node scripts/test_recording_retention.cjs` exécute les scripts réels dans un DOM
simulé avec PCM/WAV artificiel, sans microphone ni réseau. Les tests Django
utilisent également des WAV artificiels ; le test de concurrence requiert
PostgreSQL. Ces tests logiciels ne valident ni une voix ni une efficacité clinique.
