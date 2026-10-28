# rdappy

Client RDAP en ligne de commande, écrit en Python. Le programme tient dans un seul fichier et utilise uniquement la bibliothèque standard : aucune dépendance à l’exécution, aucune compilation native.

Il interroge les services de données d’enregistrement pour les domaines, les adresses et réseaux IP, les systèmes autonomes, les contacts et les serveurs DNS.

**Python 3.10 ou ultérieur · Windows, Linux et macOS · Licence Artistic 1.0 de Perl**

## Installation

Les [versions GitHub](https://github.com/koorg/rdappy/releases) proposent un paquet wheel universel. Après téléchargement :

```console
python -m pip install --user --no-deps rdappy-1.0.0-py3-none-any.whl
rdappy --version
rdappy example.com
```

Dans un environnement virtuel activé, omettre `--user`. L’installateur crée automatiquement la commande `rdappy` (`rdappy.exe` sous Windows). Son dossier de scripts doit être présent dans `PATH`. Si la commande n’est pas trouvée, redémarrer le terminal après avoir ajouté ce dossier à `PATH`, ou utiliser `python -m rdappy`.

Pour une installation isolée avec un outil `pipx` déjà disponible :

```console
pipx install ./rdappy-1.0.0-py3-none-any.whl
```

Depuis une copie du dépôt :

```console
python -m pip install --user --no-deps .
```

Cette dernière commande utilise `setuptools` pour construire le paquet ; le programme installé reste sans dépendance. L’installation depuis le wheel n’a pas besoin de `setuptools`, d’un compilateur ni d’un accès à un index de paquets.

Le dépôt est également utilisable sans installation :

```console
python rdappy.py example.com
```

## Utilisation

```console
rdappy example.com
rdappy --registry --short example.com
rdappy --both --raw rdap.org
rdappy 1.1.1.1
rdappy 2606:4700:4700::1111
rdappy 192.0.2.0/24
rdappy AS13335
rdappy --tld fr
rdappy --entity ADMIN2521-ARIN
rdappy --nameserver a.root-servers.net
rdappy --reverse 1.1.1.1
rdappy --search nic.fr
rdappy --search "exampl*.com"
rdappy https://rdap.org/domain/example.com
rdappy --file response.json --raw
rdappy --help
```

La découverte des serveurs utilise les registres de bootstrap IANA. Par défaut, rdappy suit un renvoi vers le registrar lorsqu’il existe ; si ce renvoi échoue, il affiche le résultat du registre et signale l’échec sur la sortie d’erreur.

| Option | Effet |
| --- | --- |
| `--registry` | Afficher uniquement l’objet du registre. |
| `--registrar` | Suivre le renvoi registrar ; comportement par défaut. |
| `--both` | Afficher les objets du registre et du registrar. |
| `--raw`, `--json` | Afficher les données JSON complètes. Deux objets ou plusieurs réponses de recherche sont réunis dans un tableau JSON valide. |
| `--short` | Omettre liens, remarques, avis et champs masqués. |
| `--type TYPE` | Choisir `domain`, `tld`, `ip`, `autnum`, `entity`, `nameserver` ou `url`. Les options `--domain`, `--ip`, etc. sont des alias. |
| `--server URL` | Choisir explicitement l’URL de base d’un service RDAP. |
| `--search` | Rechercher des domaines. Sans suffixe, interroger chaque service DNS IANA distinct. |
| `--reverse` | Interroger la zone DNS inverse du bloc attribué à l’IP. Pour un bloc non aligné sur une limite de zone inverse, utiliser sa zone parente couvrante. |
| `--timeout SECONDES` | Délai réseau, 20 secondes par défaut. |
| `--cache-dir DOSSIER` | Activer le cache disque ; les requêtes ordinaires sont conservées au plus 300 secondes, les bootstraps IANA au plus 24 heures. |
| `--bypass-cache` | Ignorer les caches et ne pas y écrire. |
| `--file JSON` | Lire une réponse locale sans requête RDAP. Les renvois ne sont pas suivis. |
| `--auth USER:PASS` | Authentification HTTP Basic, avec `--server` ou une URL RDAP explicite. Les identifiants ne sont jamais transmis à une autre origine ni enregistrés dans le cache. |
| `--language fr` | Choisir l’en-tête `Accept-Language` et les libellés français ; les libellés anglais sont disponibles avec `en`. |
| `--nocolor` | Désactiver les couleurs. La variable `NO_COLOR` est aussi respectée. |
| `--config FICHIER`, `--no-config` | Choisir ou ignorer le fichier de configuration. |
| `--debug` | Afficher les URL interrogées sur la sortie d’erreur. |
| `--insecure` | Désactiver la vérification des certificats TLS ; réservé aux services dont la connexion est explicitement maîtrisée. |
| `--version`, `--license` | Afficher la version ou la licence. |

Les recherches dépendent des capacités et des règles d’accès du serveur. Un serveur peut refuser les jokers ou exiger une authentification. rdappy accepte également le champ `domainSearchResult` utilisé par le serveur `.fr`. Une recherche globale peut prendre du temps ; préciser un suffixe ou `--server` limite les requêtes.

Les noms internationalisés utilisent le codec IDNA natif de Python (IDNA 2003). Certains noms IDNA 2008 exigent de fournir directement la forme ASCII acceptée par le service concerné.

Un résultat `404` signifie que l’objet est introuvable dans le service interrogé. Il ne prouve pas qu’un domaine est disponible à l’enregistrement. Les adresses privées, les préfixes de documentation et certaines ressources réservées peuvent ne pas avoir d’objet RDAP.

## Configuration

rdappy lit `~/.rdappy`, ou `~/.rdapper` si le premier n’existe pas. Le format est un argument par ligne ; les lignes vides et les commentaires commençant par `#` sont ignorés.

```text
--short
--language=fr
--timeout=15
```

Pour conserver la compatibilité avec rdapper, ces arguments sont ajoutés après ceux de la ligne de commande. Une valeur du fichier peut donc remplacer une valeur saisie dans le terminal. Utiliser `--no-config` pour un appel dont les paramètres doivent être entièrement explicites.

Sans `--cache-dir`, aucun cache persistant n’est créé. Les réponses authentifiées et celles portant `Cache-Control: no-store`, `no-cache` ou `private` ne sont pas mises en cache. Le cache optionnel contient les données RDAP reçues ; choisir un dossier dont les droits d’accès conviennent à ces données.

## Scripts et codes de retour

Les résultats sont écrits sur `stdout`. Les avertissements, diagnostics et erreurs sont écrits sur `stderr`. Les sorties de la commande installée et de `python -m rdappy` utilisent UTF-8, y compris lorsqu’elles sont redirigées.

| Code | Signification |
| --- | --- |
| `0` | Succès. Une recherche valide sans résultat est aussi un succès. |
| `1` | Échec réseau, erreur RDAP ou données invalides. |
| `2` | Arguments invalides. |
| `130` | Interruption par l’utilisateur. |

Les réponses sont limitées à 16 Mio. Les redirections HTTP(S) sont bornées, les redirections HTTPS vers HTTP sont refusées et aucun nouvel essai automatique ne contourne un code `429`.

## Construction des distributions

Le build utilise uniquement Python et `setuptools` à la version fixée dans `pyproject.toml`. Il ne compile aucun composant natif et ne télécharge rien pendant la construction.

Avec `setuptools==82.0.1` déjà installé :

```console
python tools/build.py
```

Les fichiers suivants sont créés dans `dist/` :

```text
rdappy-1.0.0-py3-none-any.whl
rdappy-1.0.0.tar.gz
rdappy.py
SHA256SUMS
```

Le wheel contient le seul module applicatif et ses métadonnées. L’archive source comprend également la documentation, les tests et l’outil de construction. Les horodatages et les métadonnées des archives sont normalisés pour rendre les builds reproductibles à sources et outils identiques. La variable `SOURCE_DATE_EPOCH` permet de fixer explicitement la date de référence.

Les tests utilisent uniquement Python et un serveur HTTP de boucle locale ; ils n’interrogent pas Internet :

```console
python -B -m unittest discover -s tests -v
```

## Licence et origine

rdappy reprend les fonctionnalités de [App::rdapper](https://github.com/gbxyz/rdapper), de CentralNic Ltd. et Gavin Brown, dans une implémentation Python distincte. Les crédits, références et différences figurent dans [NOTICE](NOTICE). La licence [Artistic 1.0 de Perl](LICENSE) est également intégrée dans le fichier applicatif pour permettre sa distribution autonome.
