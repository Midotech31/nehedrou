# Conditions de lancement et démonstration commerciale

Version du 9 octobre 2026. Le code livré peut servir à une démonstration avec données fictives. **La vente pour un usage clinique réel reste non qualifiée.** Cette fiche fixe les preuves nécessaires, sans inventer de validation, de tarif ni de résultat thérapeutique.

## Démonstration utilisable aujourd’hui

1. Ouvrir `/fr/`, `/en/` ou `/ar/` et essayer l’exemple interactif sans compte. Montrer le bénéfice : des activités choisies au cabinet, accompagnées à la maison, avec un retour pour préparer le rendez-vous.
2. Avec le compte fictif praticien : ouvrir un profil, choisir une variété, écrire un objectif et des consignes, sélectionner et ordonner les activités, puis vérifier la synthèse avant attribution.
3. Avec le compte fictif famille : commencer le parcours, retrouver son ordre, ouvrir l’activité courante et lire les consignes. Parcourir les trois étapes ou arrêter dès le début. Choisir explicitement la participation et le retour familial. Montrer la reprise et le bilan, sans compter les activités non commencées comme erreurs.
4. Revenir côté praticien : retrouver le rapport, les besoins d’aide et les arrêts de la semaine ; ajouter un retour partagé à la famille et une observation privée, puis montrer leur séparation.
5. Montrer l’impression, l’export autorisé, l’ajustement du programme, la révocation de l’accès et l’historique. Présenter l’espace éditorial et les critères de publication.

Ces étapes sont un scénario à présenter, pas un procès-verbal de recette navigateur exécutée. Les modèles audio cliniques n’étant pas fournis, ne pas laisser entendre qu’ils le sont. Aucun microphone enfant ni note de prononciation n’est proposé.

## Preuves requises avant un pilote clinique vendu

| Responsable à désigner | Livrable vérifiable | Condition de clôture |
|---|---|---|
| Orthophoniste et expert de chaque variété | Fiches et enregistrements adultes autorisés | Contrastes, transcriptions, images, consignes, population et limites réellement approuvés sur les versions exactes |
| Relecteurs natifs FR/EN/AR | Corrections du vocabulaire et des consignes | Compréhension testée ; arabe algérien évalué pour la variété visée, indépendamment de l’interface arabe standard |
| Équipe de recette | Journal desktop, 390 px, 320 px, clavier et zoom | Attribution, invitation, pratique, arrêt, erreurs, relecture et impression vérifiés dans les trois interfaces ; défauts critiques corrigés |
| Exploitant technique | Environnement PostgreSQL HTTPS, médias et SMTP | Secrets privés, MFA, contrôles d’accès, courriels reçus, supervision et récupération des comptes testés |
| Exploitant technique | Sauvegarde restaurée dans une base distincte | Comptages, médias, programmes, historique et permissions vérifiés après restauration ; tests de concurrence terminés sans interblocage |
| Responsable du service | Offre et exploitation documentées | Périmètre, entité, marché, prix/devise, support, facturation, conservation et obligations applicables définis et relus par les intervenants compétents |

Un résultat informatique d’approbation ne certifie pas la compétence d’un relecteur. La preuve d’efficacité clinique de Nehedrou, si elle est revendiquée, demande une évaluation distincte. Les essais d’utilisabilité ne la remplacent pas.

## Contrôle technique reproductible

Avec le Python de l’environnement :

```text
manage.py check
manage.py makemigrations --check --dry-run
manage.py test
scripts/check_translations.py
manage.py check_readiness --json
manage.py check_readiness --strict
```

`check_readiness` contrôle configuration, PostgreSQL, MFA, origine HTTPS, SMTP et disponibilité des versions publiées non fictives avec leurs médias et avis courants. `--strict` échoue tant qu’un contrôle technique manque. Un résultat positif ne clôture pas les conditions professionnelles et commerciales du tableau. Le rapport ne contient ni identifiants de personnes ni secrets.

Pour exercer `core.tests_concurrency`, configurer les variables PostgreSQL décrites dans `.env.example` sur un serveur fonctionnel et lancer la suite. Sous SQLite, les six tests sont explicitement ignorés, jamais comptés comme passés. La qualification 6 a exécuté les six cas sur PostgreSQL 17.11, puis restauré une base fictive dans une base distincte. Les preuves sont dans les journaux finaux et RESTAURATION_POSTGRESQL.json ; cela ne qualifie pas une exploitation de production.

## Positionnement commercial proposé

« Nehedrou aide les praticiens à préparer la pratique à domicile et les familles à suivre les activités attribuées, avec des retours accessibles avant le prochain rendez-vous. »

Ce positionnement décrit les fonctions du logiciel. Ne pas promettre de guérison, de progression automatique, de résultat garanti ou de couverture de toutes les variétés. Les 37 fiches v2 actives et leurs copies de démonstration ne sont pas des exercices cliniquement validés. Les 60 propositions v1 sont archivées, dont 23 mises en attente pour les nouvelles sélections. Le paiement en ligne n’est pas requis pour un pilote sur facture manuelle ; ses conditions doivent toutefois être définies avant toute vente.
