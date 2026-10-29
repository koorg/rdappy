# Historique des versions

## 1.1.2 — 29 octobre 2026

- Indication de pays avec origine explicite dans `--owner` : adresse du titulaire, puis enregistrement du réseau IP ou de l’ASN si nécessaire.
- Reconnaissance des noms de pays dans les adresses postales libres, dont le format ARIN, avec la liste IANA intégrée dans le domaine public.
- Codes normalisés, valeurs masquées ignorées, conflits conservés et absence de données signalée explicitement.
- Nouveau tableau JSON `country_details` avec pays, origine et URL source ; `countries` reste limité au titulaire.
- Extension des tests hors ligne et exécution de tous les tests applicatifs dans le conteneur.

## 1.1.1 — 29 octobre 2026

- Synchronisation de `fr` avec toutes les fonctions de `main` 1.1.1.
- Interface, aide, libellés et diagnostics en français, indépendamment de la locale et de la langue demandée au serveur.
- Option `--owner` centrée sur l’organisation titulaire, avec combinaison registre/registrar, filtrage des rôles et dédoublonnage.
- Sortie `--owner --raw` avec les mêmes clés JSON que l’édition anglaise ; prise en charge des domaines, réseaux IP, ASN et fichiers locaux.
- Textes Artistic et BSD-2-Clause complets dans chaque distribution et dans `--license`.
- Build Debian reproductible et indépendant de l’architecture, en bibliothèque standard.
- Conteneur français avec les tags `1.1.1-fr` et `fr` ; références de publication propres à cette édition.
- Audit des sources, de l’historique et des archives pour détecter les identifiants du poste et du profil.
- Métadonnées d’auteur et de maintenance limitées au pseudo GitHub `koorg`.
- Reprise de tous les tests 1.1.1 et contrôles supplémentaires de l’interface française et de la compatibilité JSON.

## 1.1.0 — 28 octobre 2026

- Ajout, dans l’édition anglaise, du résumé `--owner` des organisations, noms, courriels et pays des contacts titulaires.
- Combinaison registre/registrar par défaut dans ce mode, avec sélection explicite d’une source possible.
- Exclusion des contacts du registrar, techniques, administratifs, d’abus et des titulaires imbriqués sous un tiers.

## 1.0.1 — 28 octobre 2026

- Édition anglaise principale sur `main` et conservation de l’édition française sur `fr`.
- Aide, diagnostics et libellés anglais indépendants de la langue du système sur `main`.

## 1.0.0 — 28 octobre 2026

- Version initiale du client RDAP Python en un seul fichier.
- Commande `rdappy`, wheel universel, archive source et licences incluses.
- Requêtes de domaines, réseaux IP, ASN, contacts et serveurs DNS, recherche, DNS inverse et lecture de fichiers JSON.
