# Parcours de pratique — livraison du 9 octobre 2026

Un programme comporte désormais un parcours que son accompagnant peut commencer, interrompre temporairement, reprendre et terminer. Le praticien autorisé retrouve le bilan dans le programme. Ce parcours regroupe des rapports d’activité ; il ne représente ni une séance de soins ni une mesure de progrès de parole.

## Utilisation

1. Depuis l’accueil familial ou le programme, choisir **Commencer le parcours**.
2. Consulter la liste prévue, les consignes du praticien et le nombre d’activités avec compte rendu, puis poursuivre l’activité courante.
3. Enregistrer explicitement la réalisation ou l’arrêt, le ressenti et un commentaire facultatif. L’activité suivante est proposée après l’enregistrement, sans obligation de poursuivre.
4. **Faire une pause et revenir plus tard** conserve la place et les rapports enregistrés. Les réponses et commentaires non soumis dans l’activité doivent être enregistrés avant de quitter pour être conservés.
5. **Terminer ce parcours** le clôture sans inventer de rapport sur les activités non commencées. Un arrêt rapporté pendant une activité clôture aussi le parcours. Les activités restantes restent non commencées et ne comptent pas comme des erreurs.
6. Une nouvelle pratique d’un programme actif crée un nouveau parcours après la clôture du précédent. Les parcours et rapports précédents restent consultables.

Une activité retirée ou devenue indisponible n’est jamais sautée pour atteindre la suivante. Le parcours indique le blocage et permet de le clôturer. Un programme ajusté conserve l’ancien historique et utilise de nouveaux items. La clôture du programme ou l’archivage du profil empêche toute nouvelle réponse.

## Continuité et droits

- L’ordre, les identifiants des activités, la cible de l’essai et le nonce sont conservés dès le démarrage. Recharger la page ne tire pas un nouvel essai.
- Une seule pratique active par utilisateur et programme. Un double démarrage retrouve ce parcours. Un même envoi accepté renvoie le même rapport ; un contenu différent avec le même ticket est refusé.
- Le serveur n’accepte que la prochaine activité exacte et un ticket signé lié à l’utilisateur, au parcours, à l’item, à la position et à l’essai. Chaque tâche reçoit au plus un rapport.
- Un accompagnant reprend uniquement son propre parcours dans un dossier actuellement autorisé. Le praticien responsable peut lire le bilan familial, sans répondre au nom de l’accompagnant ni clôturer son parcours.
- Les accès révoqués restent refusés, même avec un ancien ticket. Les anciens rapports individuels demeurent disponibles ; ils ne sont pas convertis artificiellement en parcours.
- L’export autorisé inclut les parcours et les liens vers leurs rapports. La procédure d’effacement sous rétention supprime explicitement les rapports, les parcours puis les programmes.

## Preuves et limites

La suite complète a découvert **89 tests : 83 réussis, 6 ignorés**, en 93,818 secondes sur SQLite avec code de sortie 0. Seize tests couvrent spécialement le parcours ; trois nouveaux tests PostgreSQL couvrent les départs simultanés, la retransmission de dernière activité et le conflit entre réponse et clôture. Ces trois tests, et les trois tests PostgreSQL antérieurs, restent non exécutés ici. SQLite ne valide pas les verrous PostgreSQL.

Douze vérifications HTTP avec CSRF ont été exécutées sur le serveur de E: dans les trois langues : accueil et exemple public, espace praticien, départ répété/reprise stable et clôture avec ou sans rapport. Les programmes utilisés sont fictifs. Les tests HTTP ne rendent pas la page, n’exécutent pas son JavaScript et ne constituent pas une recette visuelle.

Les nouveaux textes sont livrés en français, anglais et arabe ; Tajawal locale et RTL sont conservés. La relecture native et les essais avec familles/praticiens ne sont pas acquis. Aucun catalogue clinique ou modèle audio approuvé n’est fabriqué par cette fonctionnalité.
