# rdappy — édition française

Client RDAP en ligne de commande, écrit en Python. Le programme tient dans un seul fichier et utilise uniquement la bibliothèque standard : aucune dépendance à l’exécution, aucune compilation native.

Il interroge les données d’enregistrement des domaines, des adresses et réseaux IP, des systèmes autonomes, des contacts, des organisations, des mainteneurs et des serveurs DNS. Les chemins RDAP et les paramètres libres donnent aussi accès aux recherches et aux extensions proposées par chaque service.

**Python 3.10 ou ultérieur · Windows, Linux et macOS · Artistic-1.0-Perl AND BSD-2-Clause**

La branche `fr` fournit l’édition française 1.2.0. Elle reprend les fonctions de l’édition anglaise 1.1.2 de [`main`](https://github.com/koorg/rdappy/tree/main) et étend les requêtes et recherches RDAP. L’aide, les libellés et les diagnostics restent en français, indépendamment de la langue du système. Les valeurs reçues des serveurs sont conservées telles quelles.

## Installation

La dernière [release française précompilée, 1.1.2](https://github.com/koorg/rdappy/releases/tag/fr-v1.1.2), propose un wheel universel et un paquet Debian. Pour disposer des nouvelles requêtes de la version 1.2.0, utiliser les sources de la branche `fr` selon les instructions ci-dessous. Après téléchargement du wheel 1.1.2 :

```console
python -m pip install --user --force-reinstall --no-deps rdappy-1.1.2-py3-none-any.whl
rdappy --version
rdappy --owner example.com
```

Omettre `--user` dans un environnement virtuel activé. L’installateur crée la commande `rdappy` (`rdappy.exe` sous Windows). Le dossier des scripts Python doit être dans `PATH`. Après l’avoir ajouté, ouvrir un nouveau terminal, ou utiliser `python -m rdappy`.

Les deux éditions utilisent le même nom de paquet et la même commande. `--force-reinstall` permet de remplacer une édition anglaise de même version par le wheel français. Utiliser des environnements virtuels distincts pour conserver les deux éditions.

Avec une installation existante de `pipx` :

```console
pipx install ./rdappy-1.1.2-py3-none-any.whl
```

Depuis les sources :

```console
git clone --branch fr --single-branch https://github.com/koorg/rdappy.git
cd rdappy
python -m pip install --user --no-deps .
```

L’installation depuis les sources utilise `setuptools` pour construire le paquet. Le wheel ne nécessite ni `setuptools`, ni compilateur, ni accès à un index de paquets. Le fichier autonome fonctionne aussi directement :

```console
python rdappy.py --owner example.com
```

### Debian et Ubuntu

Télécharger le `.deb` de la release française, puis l’installer :

```console
sudo apt install --reinstall ./rdappy_1.1.2_all.deb
rdappy --owner example.com
```

Le paquet fournit `/usr/bin/rdappy` et requiert Python 3.10 ou ultérieur. Il ne contient aucun script de maintenance et ne télécharge rien pendant son installation. `apt` peut installer Python si cette dépendance manque. Les licences sont dans `/usr/share/doc/rdappy/`. Désinstaller avec `sudo apt remove rdappy`.

### GitHub Packages

Le conteneur Linux amd64 français utilise les tags `1.1.2-fr` et `fr` dans [GitHub Packages](https://github.com/users/koorg/packages/container/package/rdappy) :

```console
docker run --rm ghcr.io/koorg/rdappy:1.1.2-fr --owner example.com
docker run --rm ghcr.io/koorg/rdappy:fr --license
```

Il fonctionne avec un utilisateur numérique sans privilèges. Un paquet privé peut nécessiter `docker login ghcr.io`. Les fichiers wheel et Debian sont joints aux releases ; la rubrique Packages contient le conteneur. Les tags `1.1.2` et `latest` identifient l’édition anglaise.

## Utilisation

```console
rdappy example.com
rdappy --owner example.com
rdappy --owner 1.1.2.1
rdappy --registry --short example.com
rdappy --both --raw rdap.org
rdappy 1.1.2.1
rdappy 2606:4700:4700::1111
rdappy 192.0.2.0/24
rdappy AS13335
rdappy --tld fr
rdappy --entity ADMIN2521-ARIN
rdappy MNT-ADSI
rdappy /entity/MNT-ADSI
rdappy --nameserver a.root-servers.net
rdappy --reverse 1.1.2.1
rdappy --search nic.fr
rdappy --search "exampl*.com"
rdappy https://rdap.org/domain/example.com
rdappy --file response.json --raw
rdappy --help
```

La découverte des services utilise les registres bootstrap de l’IANA. Par défaut, rdappy suit le renvoi vers le registrar lorsqu’il existe. Si cette requête échoue, il affiche la réponse du registre et écrit un avertissement sur la sortie d’erreur.

| Option | Comportement |
| --- | --- |
| `--owner` | Résumé du titulaire, centré sur son organisation. Pour un domaine, combine registre et registrar par défaut. |
| `--registry` | Afficher uniquement la réponse du registre. |
| `--registrar` | Suivre le renvoi vers le registrar ; comportement normal par défaut. |
| `--both` | Afficher les réponses du registre et du registrar. |
| `--raw`, `--json` | Afficher le JSON complet. Plusieurs réponses sont réunies dans un tableau JSON valide. |
| `--short` | Omettre liens, remarques, avis et champs masqués. |
| `--type TYPE` | Imposer `domain`, `tld`, `ip`, `autnum`, `entity`, `nameserver`, `url`, `path` ou `help`. Les options `--domain`, `--ip`, etc. sont des alias ; `--rdap-help` choisit l’aide distante. |
| `--server URL` | Choisir explicitement l’URL de base du service RDAP. |
| `--search` | Rechercher des domaines par défaut, ou choisir `--type entity`, `nameserver`, `ip` ou `autnum`. Seule la recherche de domaine par nom dispose de la découverte IANA ; sans suffixe, elle interroge chaque service DNS IANA distinct. |
| `--search-field CHAMP` | Choisir le champ recherché selon le type : `name`, `nsLdhName`, `nsIp`, `ip`, `fn` ou `handle`. |
| `--path CHEMIN` | Interroger un chemin relatif au service, avec sa query string éventuelle. Les chemins connus comme `/entity/MNT-ADSI` sont également reconnus sans cette option. |
| `--param NOM=VALEUR` | Ajouter un paramètre à la requête initiale, y compris aux URL explicites. Option répétable ; les clés répétées et les valeurs vides sont conservées. |
| `--rdap-help` | Consulter `/help` sur le `--server` indiqué, sans objet ; afficher ses avis et ses extensions RDAP. `--help` reste l’aide locale. |
| `--reverse` | Interroger la zone DNS inverse du bloc IP attribué ; utiliser sa zone parente pour un bloc non aligné. |
| `--timeout SECONDES` | Délai réseau par requête ; 20 secondes par défaut. |
| `--cache-dir DOSSIER` | Activer le cache disque : au plus 300 secondes pour les réponses et 24 heures pour les bootstraps IANA. |
| `--bypass-cache` | Ignorer les caches et ne pas y écrire. |
| `--file JSON` | Lire une réponse locale sans requête RDAP ni renvoi vers le registrar. |
| `--auth USER:PASS` | Authentification HTTP Basic avec `--server` ou une URL explicite. Les identifiants restent limités à l’origine interrogée et ne sont jamais mis en cache. |
| `--language LANGUE` | En-tête `Accept-Language`, `fr` par défaut. L’interface reste en français ; la langue des données dépend du serveur. |
| `--nocolor` | Désactiver les couleurs ANSI. La variable `NO_COLOR` est également respectée. |
| `--config FICHIER`, `--no-config` | Choisir ou ignorer le fichier de configuration. |
| `--debug` | Afficher les URL interrogées sur la sortie d’erreur. |
| `--insecure` | Désactiver la vérification TLS pour un service dont la connexion est explicitement maîtrisée. |
| `--version`, `--license` | Afficher la version ou les deux licences complètes. |

Les recherches dépendent des capacités et des règles d’accès du serveur. Certains services refusent les jokers ou exigent une authentification. rdappy accepte le champ non standard `domainSearchResult` du service `.fr`. Une recherche globale peut être longue ; préciser un suffixe ou `--server` pour limiter les requêtes.

Les noms internationalisés utilisent le codec IDNA intégré de Python (IDNA 2003). Pour certains noms IDNA 2008, fournir directement la forme ASCII acceptée par le service.

Une réponse `404` signifie que le service interrogé n’a pas trouvé l’objet. Elle ne prouve pas qu’un domaine est disponible à l’enregistrement. Les adresses privées, les préfixes de documentation et certaines ressources réservées peuvent ne pas avoir de réponse RDAP.

## Entités, recherches et extensions RDAP

Dans la base RIPE, les objets PERSON, ROLE, ORGANISATION et MNTNER sont tous accessibles sous `/entity/IDENTIFIANT`. Il n’est donc pas nécessaire d’ajouter un type `mntner` distinct. Les handles usuels comme `ADSI2-RIPE`, `ORG-EXAMPLE-RIPE`, `MNT-ADSI` ou `EXAMPLE-MNT` sont reconnus automatiquement ; `--entity` permet de choisir ce type pour tout autre identifiant.

```console
rdappy MNT-ADSI
rdappy --entity ADSI2-RIPE
rdappy --server https://rdap.db.ripe.net/ --entity MNT-ADSI
rdappy https://rdap.db.ripe.net/entity/MNT-ADSI
rdappy --server https://rdap.db.ripe.net/ --rdap-help
```

Les tags enregistrés à l’IANA priment pour découvrir le service des entités. À défaut de tag reconnu, les conventions `MNT-…`, `…-MNT` et `ORG-…` orientent vers le service RIPE déclaré à l’IANA. Ces conventions ne garantissent pas l’unicité mondiale d’un identifiant : utiliser `--server` ou l’URL complète pour choisir précisément sa base. Les autres identifiants sans tag exigent un serveur explicite.

Les recherches structurées couvrent les champs de la [RFC 9082](https://www.rfc-editor.org/rfc/rfc9082.html) et les recherches IP/ASN de la [RFC 9910](https://www.rfc-editor.org/rfc/rfc9910.html) :

| Type (`--type`) | Chemin | Champs (`--search-field`) | Champ par défaut |
| --- | --- | --- | --- |
| `domain` | `/domains` | `name`, `nsLdhName`, `nsIp` | `name` |
| `nameserver` | `/nameservers` | `name`, `ip` | `name` |
| `entity` | `/entities` | `fn`, `handle` | `fn` |
| `ip` | `/ips` | `name`, `handle` | `name` |
| `autnum` | `/autnums` | `name`, `handle` | `name` |

```console
rdappy --server https://rdap.db.ripe.net/ --search --entity --search-field handle "MNT-ADSI"
rdappy --server https://rdap.db.ripe.net/ --search --entity "Amazon Data Services Ireland*"
rdappy --server https://rdap.verisign.com/com/v1/ --search --nameserver --search-field ip 216.239.32.10
rdappy --server https://rdap.arin.net/registry/ --search --ip --search-field handle "NET-149-112-152-0-*"
rdappy --server https://rdap.arin.net/registry/ --search --autnum --search-field name "ARIN*"
```

Les champs IP des recherches DNS attendent une adresse seule, sans préfixe CIDR. Les noms d’entité et de réseau sont des textes libres ; ils ne passent pas par la validation des noms DNS. Les paramètres sont encodés en UTF-8 et les recherches textuelles normalisées en NFC. Hors `domain/name`, un serveur explicite est nécessaire, car le motif ne permet pas de déterminer un registre compétent.

Pour les recherches inversées par contact, les relations entre ressources, les identifiants de réseau propres à un registre et les autres extensions, fournir le chemin du service ou son URL complète :

```console
rdappy --server https://rdap.arin.net/registry/ --path "ips/rirSearch1/rdap-up/149.112.152.0/22"
rdappy --server https://rdap.arin.net/registry/ --path "domains/rirSearch1/rdap-down/152.112.149.in-addr.arpa"
rdappy --server https://rdap.arin.net/registry/ --path "ips/reverse_search/entity?handle=ARINL"
rdappy --server https://rdap.arin.net/registry/ --path "autnums/reverse_search/entity?fn=ARIN"
rdappy --server https://rdap.arin.net/registry/ --path "arin_originas0_networksbyoriginas/10745"
rdappy --server https://rdap.db.ripe.net/ --path entities --param "handle=MNT-ADSI"
rdappy --server https://rdap.arin.net/registry/ --path "ips?name=EXAMPLE*" --param count=true --param limit=10 --raw
```

`--path` conserve le préfixe de l’URL de base (par exemple `/registry/`), les paramètres déjà encodés et les paramètres répétés. Il accepte aussi les chemins d’extensions inconnus du client. Ces chemins exigent `--server` ; les consultations simples `domain/…`, `ip/…`, `autnum/…`, `entity/…` et `nameserver/…` peuvent découvrir leur service via l’IANA. La présence d’un chemin ou d’un paramètre dans le client ne signifie pas que tous les serveurs l’implémentent : consulter leur `/help` et leur documentation. Par exemple, Verisign propose la recherche de serveurs DNS par IP, et refuse la recherche par nom. Certaines extensions renvoient uniquement des notices lorsqu’elles n’ont pas de résultat ; ces notices restent affichables sans imposer `--raw`.

Les résultats de recherche restent une liste d’identifiants sur la sortie texte. Les recherches IP/ASN sans identifiant affichent leur nom ou leur plage. Les tableaux de résultats d’extensions comme `arin_originas0_networkSearchResults` sont également reconnus. `--raw` conserve l’enveloppe JSON, les notices et les extensions du serveur, y compris `ipSearchResults` et `autnumSearchResults`. Les réseaux et ASN inclus dans une fiche d’entité sont également affichés en mode détaillé.

Dans les objets lien RDAP, `value` décrit le contexte du lien ; `href` est sa destination. Copier une de ces URL pour l’interroger ne lance aucune exploration récursive des liens de la réponse.

## Résumé de l’organisation titulaire

```console
rdappy --owner example.com
rdappy --owner 1.1.2.1
rdappy --owner AS13335
rdappy --owner --raw example.com
rdappy --owner --registry example.com
rdappy --owner --file response.json
```

`--owner` affiche l’objet interrogé, les organisations titulaires, les noms des contacts, leurs pays et leurs courriels. L’organisation apparaît en premier. Les champs absents sont omis ; une organisation non disponible est signalée par `Non divulguée ou non fournie`.

Seules les entités portant directement le rôle `registrant` sur l’objet interrogé sont utilisées. Les contacts du registrar, techniques, administratifs ou d’abus sont exclus, ainsi que les titulaires imbriqués sous un contact tiers. Le nom d’un réseau n’est jamais assimilé à une organisation. Le nom formaté d’un contact sert d’organisation uniquement si sa jCard indique explicitement `kind=org`.

Pour les domaines, les deux sources sont combinées et les doublons supprimés. `--registry` et `--registrar` sélectionnent une seule source. `--owner --raw` conserve les clés JSON `object_type`, `object`, `organizations`, `registrants`, `emails`, `countries`, `sources` et `country_details`, identiques à celles de l’édition anglaise. Sans `--owner`, `--raw` fournit la réponse RDAP complète.

Le résumé prend en charge les réseaux IP, les ASN et les fichiers JSON locaux. Il est incompatible avec `--search`. Le pays provient de l’adresse du contact titulaire et ne constitue pas une géolocalisation IP. Le titulaire d’un réseau peut être un opérateur ou un hébergeur ; celui d’un domaine peut être un service de confidentialité. Les données non publiées ne peuvent pas être déduites de ce résumé.

### Indication de pays

Le libellé indique la nature du pays affiché :

- `Pays (titulaire)` : pays de l’adresse du contact titulaire direct. Le paramètre `cc` prime sur le champ pays structuré, puis sur un nom de pays reconnu à la dernière ligne d’une adresse postale libre.
- `Pays (enregistrement du réseau)` ou `Pays (enregistrement ASN)` : champ `country` de la fiche RDAP, utilisé seulement si aucune adresse du titulaire ne fournit de pays exploitable.
- `Pays: Non communiqué ou non fourni` : absence de pays public utilisable. Les pays publiés en désaccord sont conservés.

Les noms de pays sont reconnus grâce à la liste IANA intégrée au programme, dans le domaine public, et à des alias usuels. Les noms reconnus et les codes sont normalisés en codes à deux lettres. Une ligne isolée `CA`, `LA` ou `Georgia` dans une adresse libre reste ambiguë avec une région administrative et n’est pas utilisée pour déduire un pays.

Il s’agit de données administratives d’enregistrement, pas d’une géolocalisation physique de l’IP. Le suffixe d’un domaine, l’adresse du registrar ou la localisation de l’hébergement ne servent pas à déduire le pays du titulaire. Aucun service supplémentaire ni base externe n’est interrogé.

Dans `--owner --raw`, `countries` reste limité aux pays des adresses du titulaire. Le nouveau tableau `country_details` contient les indications retenues avec `country`, `basis` (`registrant_address`, `network_registration` ou `autnum_registration`) et `source` (URL RDAP ou URI du fichier local). Les preuves répétées sont dédoublonnées.

Ces champs suivent [les données d’enregistrement RDAP](https://www.rfc-editor.org/rfc/rfc9083.html#section-5.4) et [le paramètre pays de vCard](https://www.rfc-editor.org/rfc/rfc8605.html#section-3.1).

## Configuration

rdappy lit `~/.rdappy`, puis `~/.rdapper` si le premier fichier n’existe pas. Fournir un argument par ligne. Les lignes vides et les commentaires commençant par `#` sont ignorés.

```text
--short
--language=fr
--timeout=15
```

Pour rester compatible avec rdapper, ces arguments sont ajoutés après ceux de la ligne de commande. Une valeur du fichier peut donc remplacer une valeur saisie dans le terminal. Utiliser `--no-config` pour imposer uniquement les arguments explicites.

L’aide, les libellés et les diagnostics restent en français même avec `--language=en` ou une locale système anglaise. `--language` choisit uniquement la langue demandée au service RDAP.

Aucun cache persistant n’est créé sans `--cache-dir`. Les réponses authentifiées ou portant les directives `Cache-Control: no-store`, `no-cache` ou `private` ne sont pas mises en cache. Un cache facultatif contient des données RDAP reçues ; choisir un dossier dont les droits d’accès conviennent à ces données.

## Scripts et codes de sortie

Les résultats sont écrits sur `stdout`. Les avertissements, diagnostics et erreurs sont écrits sur `stderr`. La commande installée et `python -m rdappy` utilisent UTF-8, y compris après redirection.

| Code | Signification |
| --- | --- |
| `0` | Succès. Une recherche valide sans résultat réussit également. |
| `1` | Échec réseau, erreur RDAP ou données invalides. |
| `2` | Arguments invalides. |
| `130` | Interruption par l’utilisateur. |

Les réponses sont limitées à 16 Mio. Le nombre de redirections HTTP(S) est borné, les redirections HTTPS vers HTTP sont refusées et aucune nouvelle tentative automatique ne contourne une réponse `429`.

## Construction des distributions

Le build utilise Python et la version de `setuptools` fixée dans `pyproject.toml`. Il ne compile aucun composant natif et ne télécharge rien. Avec `setuptools==82.0.1` déjà installé :

```console
python -B tools/build.py
```

Le dossier `dist/` contient :

```text
rdappy-1.2.0-py3-none-any.whl
rdappy-1.2.0.tar.gz
rdappy_1.2.0_all.deb
rdappy.py
SHA256SUMS
```

Le wheel contient le module applicatif et ses métadonnées. L’archive source comprend documentation, tests et outils de construction. Les horodatages et propriétaires des archives sont normalisés pour reproduire les builds à sources et outils identiques. `SOURCE_DATE_EPOCH` permet de choisir explicitement l’horodatage de référence.

Construire uniquement le paquet Debian avec la bibliothèque standard, sans `setuptools` ni outil de build Debian :

```console
python -B tools/build.py --deb-only
```

Les métadonnées d’auteur et de maintenance utilisent le pseudo GitHub `koorg`. Auditer les sources, l’historique Git et les archives explicitement nommées, sans afficher les identifiants du poste :

```console
python -B tools/audit_distribution.py --history --github-profile dist/rdappy-1.2.0-py3-none-any.whl dist/rdappy-1.2.0.tar.gz dist/rdappy_1.2.0_all.deb
```

Omettre `--github-profile` pour un audit entièrement hors ligne. Les identifiants du poste local restent vérifiés. Le contexte de construction du conteneur se limite au programme et aux fichiers de licence.

Les tests utilisent Python et un serveur HTTP de boucle locale ; ils ne consultent pas Internet :

```console
python -B -m unittest discover -s tests -v
```

## Licence et origine

rdappy implémente les fonctions de [App::rdapper](https://github.com/gbxyz/rdapper), de CentralNic Ltd. et Gavin Brown, dans un programme Python distinct. Les crédits, références et différences figurent dans [NOTICE](NOTICE).

Le programme utilise la [licence Artistic 1.0 de Perl](LICENSE). Les adaptations issues de Net::RDAP conservent ses [conditions et sa clause de non-responsabilité BSD-2-Clause](LICENSES/BSD-2-Clause.txt). L’expression de licence de la distribution est `Artistic-1.0-Perl AND BSD-2-Clause`. Les deux textes complets sont intégrés au fichier autonome et inclus dans le wheel, l’archive source, le paquet Debian et le conteneur. `rdappy --license` les affiche. Les mentions des auteurs amont sont conservées conformément à leurs licences.
