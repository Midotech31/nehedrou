# Recette PostgreSQL 17 sur données fictives

Cette recette lance un nouveau cluster PostgreSQL 17 sur l’interface locale, applique les migrations du checkout examiné, puis exerce la sauvegarde chiffrée et la restauration réelles de Nehedrou. Elle compare les empreintes des lignes, les définitions de clés étrangères, les séquences et les octets des médias. Après restauration, elle vérifie les exports professionnel et familial, le refus d’un compte tiers et la conservation des invitations et documents fictifs. La recette retrouve aussi le justificatif et l’origine d’une prise, puis ouvre la comparaison d’un guide conservé dans une copie privée.

## Exécution

Utiliser l’environnement Python du projet avec ses dépendances verrouillées et les binaires PostgreSQL 17 côté client et serveur. Ouvrir le terminal à la racine du checkout. Indiquer le chemin **du dossier des binaires** et, pour enregistrer la recette ailleurs que dans le dossier temporaire du système, un parent existant **hors du checkout**.

```powershell
python -B scripts/restore_regression/run_local_postgres.py --repository . --pg-bin E:/outils/postgres17/bin --work-dir E:/NehedrouTestTemp
```

`initdb` et `pg_ctl` s’exécutent sous le compte local. Sur Linux, utiliser un compte sans privilèges d’administration. Sur Windows, les politiques qui bloquent les sous-processus PostgreSQL peuvent nécessiter un terminal autorisé à les lancer. Le serveur écoute sur `127.0.0.1` avec authentification SCRAM et mots de passe créés uniquement pour l’essai.

Le résultat JSON final indique le chemin de `summary.json`. Le reçu n’attribue les résultats à un commit exact que si le checkout est propre et sur le même commit avant et après l’essai. Le runner arrête son cluster et retire le fichier temporaire du mot de passe. Les données et journaux de diagnostic fictifs restent dans le sous-dossier de l’essai, pour contrôle local.

## Portée

La recette ne requiert aucun service hébergé, secret de production ou dossier réel. Elle vérifie un schéma et des données fictives avec les primitives de sauvegarde et de restauration du checkout, sur un même serveur PostgreSQL 17 isolé. La vérification des exports appelle les vues avec des identités fictives et un accès en lecture seule. L’écriture de leur événement d’audit est neutralisée pendant cette étape. Le manifeste WhiteNoise est compilé dans le dossier de la recette avec `DEBUG=0` pour vérifier le rendu du guide restauré.

Le déclenchement périodique, la copie hors machine, la reprise des services, le stockage distant, les engagements de reprise et la recette de connexion navigateur se vérifient séparément avec la [procédure d’exploitation](../../docs/EXPLOITATION.md).
