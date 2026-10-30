# Diagnostic et transports des courriels

État du code au 30 octobre 2026. Aucun compte fournisseur, clé, domaine, envoi ou réception n’a été créé ou vérifié dans ce lot. Le transport HTTPS reste désactivé par défaut (`RESEND_ENABLED=False`) ; le backend par défaut en mode non DEBUG est `core.email_backends.DisabledEmailBackend`. La console reste le défaut local en DEBUG. L’expéditeur par défaut du projet utilise un domaine d’exemple et ne satisfait pas le diagnostic d’envoi réel.

## Transport sélectionné

`EMAIL_BACKEND` choisit explicitement le transport. Aucune configuration de clé ne sélectionne automatiquement Resend et aucun échec ne déclenche un repli vers un autre transport.

| Sélection | Diagnostic |
| --- | --- |
| `django.core.mail.backends.smtp.EmailBackend` | Serveur, port, mode chiffré unique, délai borné, présence des identifiants et syntaxe de l’expéditeur avec domaine hors exemples. |
| `core.email_backends.ResendEmailBackend` | Activation explicite, présence d’une clé locale utilisable, délais de connexion et de lecture bornés, syntaxe de l’expéditeur avec domaine hors exemples. |
| Backend désactivé, console locale ou backend non pris en charge | Aucun transport de livraison prêt. Une valeur arbitraire de backend n’est jamais recopiée dans le rapport. |

Le backend Resend utilise le point d’entrée HTTPS fixe prévu par l’implémentation. Le diagnostic ne contacte pas ce service : il ne vérifie ni la clé auprès du fournisseur, ni le domaine, ni les DNS, ni l’acceptation du message, ni sa réception. Une déclaration `configured=true` décrit exclusivement les champs locaux requis.

Les réglages HTTPS sont `RESEND_ENABLED` (désactivé par défaut), `RESEND_API_KEY` (vide par défaut), `EMAIL_HTTP_CONNECT_TIMEOUT` (5 secondes par défaut, intervalle 1 à 15) et `EMAIL_HTTP_READ_TIMEOUT` (10 secondes par défaut, intervalle 1 à 30). Les valeurs sensibles doivent rester dans la configuration privée de l’exploitant. Elles n’apparaissent jamais dans les JSON ou la page de diagnostic.

## Rapports et accès

Le schéma `nehedrou-operations-readiness-v1` conserve sa section historique `smtp`. La nouvelle section `email` indique uniquement le backend parmi `smtp`, `resend`, `disabled`, `console`, `unsupported`, le transport parmi `smtp`, `https`, `none`, les contrôles booléens, les codes de manques et les résultats `network_attempted=false`, `delivery_verified=false`. Les adresses, noms de serveurs, domaines, clés et corps de messages sont exclus de cette sortie.

`configuration_ready` et le contrôle `email_configured` de `check_readiness` suivent le backend sélectionné. Les champs SMTP historiques ne bloquent pas le diagnostic d’un backend HTTPS correctement configuré. Aucun de ces résultats ne signifie qu’un courriel a été reçu. Le backend désactivé échoue sans écrire de message ou de jeton dans la console ; il empêche ainsi un repli implicite vers une sortie contenant des liens de récupération ou d’invitation sur un serveur non DEBUG.

La page `/fr/operations/` et ses équivalents EN/AR gardent leur permission privée `core.manage_entitlements` et le contrôle MFA existant. GET et HEAD n’effectuent aucun appel réseau ni envoi. Le seul test POST proposé reste `SELECT 1` sur la base ; un POST demandant un envoi ou une autre action est refusé. La page n’expose aucun dossier clinique et ses réponses sont privées, `no-store`.

## Limite de Render Free

La documentation officielle de [Render Free](https://render.com/docs/free) indique que ses services web gratuits bloquent le trafic SMTP sortant sur les ports 25, 465 et 587. Un diagnostic SMTP local positif ne peut donc pas établir la livraison depuis ce plan. Le constat vient de la documentation, pas d’un essai réseau réalisé dans ce lot.

Le choix d’un transport HTTPS exige encore l’activation autorisée par l’exploitant, une configuration fournisseur et expéditeur réelle, puis une recette d’envoi/réception explicitement autorisée dans les parcours de récupération et d’invitation. Le diagnostic de configuration ne marque aucune de ces étapes terminée.

## Vérification

`core.tests_email_readiness` vérifie le choix SMTP/HTTPS, le transport désactivé, la clé absente ou impropre, les expéditeurs réservés, les délais, l’absence de repli, les rapports privés, la provenance du processus et les contrôles d’accès HTTP. Les tests utilisent uniquement des identifiants fictifs et des mocks réseau ; aucun trafic fournisseur ou SMTP externe n’est attendu.

## Contrat du transport HTTPS

L’implémentation ne dépend d’aucun nouveau paquet. Elle utilise la bibliothèque standard Python, TLS avec vérification des certificats, l’hôte fixe `api.resend.com:443` et `POST /emails`. Aucun paramètre utilisateur ne choisit la destination réseau. Les clés et adresses sont contrôlées avant d’ouvrir une connexion. Le diagnostic réutilise ces contrôles locaux.

Le sous-ensemble actuel transporte les messages texte des invitations et de récupération, avec un seul complément HTML possible. Les autres types MIME, pièces jointes, CC/BCC, Reply-To, en-têtes supplémentaires et encodages différents d’UTF-8 sont refusés explicitement. Ils ne sont pas supprimés silencieusement. Une adresse d’expéditeur différente de celle configurée est refusée ; la présentation utilisée reste celle de la configuration. Le corps complet est limité à 1 Mio après sérialisation JSON.

Une réponse HTTP 2xx compte comme acceptation seulement si son JSON borné à 64 Kio contient un identifiant opaque non vide conforme au format pris en charge. Ce n’est pas une confirmation de réception. Un refus, une redirection, un délai expiré ou une réponse incorrecte déclenche une erreur générique ; aucun texte fournisseur, destinataire, clé ou lien n’est inclus dans l’exception. La connexion est fermée après chaque tentative. Il n’existe ni suivi de redirection, ni repli, ni nouvelle tentative automatique. Chaque envoi intentionnel crée une clé d’idempotence distincte. Les délais de socket bornés ne sont pas une garantie de délai total de bout en bout, notamment pour la résolution DNS.

Ces contrats s’appuient sur [l’API officielle d’envoi Resend](https://resend.com/docs/api-reference/emails/send-email) ; les comptes, quotas, autorisations du domaine et conditions du fournisseur restent à vérifier par l’exploitant avant activation.

## Invitations et récupération

Une invitation n’est marquée `sent` qu’après l’acceptation du transport ; la signification existante reste « remise au service d’envoi », jamais « reçue ». Une erreur laisse l’invitation enregistrée avec le statut `failed`, permettant une nouvelle tentative qui révoque l’ancien lien. Les contrôles de cabinet, de rôle, de destinataire, d’expiration et d’usage unique restent appliqués.

Le formulaire de récupération conserve les jetons Django, leur expiration, leur usage unique et la réponse neutre pour un compte inconnu ou un échec de transport. Il construit maintenant l’adresse complète du lien depuis `PUBLIC_ORIGIN`, indépendamment du Host de la requête, y compris un alias autorisé. Cette origine doit être une origine HTTP(S) complète, sans identifiants, chemin supplémentaire, query, fragment, caractères de contrôle, espace ou antislash ; une valeur incorrecte arrête le démarrage avec un message générique. Le diagnostic de lancement exige HTTPS. HTTP reste disponible pour le développement local.

Les tests des parcours utilisent le vrai backend avec uniquement `HTTPSConnection` simulé. Les liens, langues et autorisations sont traités par les vues et services réels sur des comptes fictifs. Ils ne contactent aucun fournisseur et ne démontrent pas la réception dans une boîte réelle.
