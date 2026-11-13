# Portech ERP : corrections et améliorations (12 novembre 2026)

Tous les changements ont été testés sur une copie de l'ERP qui tournait avec les données de ta sauvegarde du 1er novembre :
- les 29 onglets ont été ouverts un à un : aucune erreur ;
- 103 adresses de l'API ont été appelées : aucune erreur ;
- un scénario complet a été rejoué (client → soumission → facture → paiements → relance → état de compte → annulation → bon de commande → connaissement → dépense → kilométrage → job) ;
- le site a été compilé en version de production sans erreur.

## Ce que tu as demandé

| Demande | Ce qui a été fait | Fichiers |
|---|---|---|
| Relances utilisables | Les relances de factures sont maintenant **activées par défaut**. Un nouvel encadré **Factures → Envois automatiques** permet de les activer ou désactiver sans redéployer. Il montre aussi la liste des factures qui seront relancées au prochain passage de 8 h, signale les clients sans courriel et offre un bouton « Envoyer maintenant ». Les états de compte mensuels et les suivis de soumissions ont maintenant le même interrupteur ; ils restent désactivés tant que tu ne les actives pas. | `erp_automations.py` (nouveau), `erp_reminders.py`, `erp_routes_statements.py`, `erp_routes_quotes.py`, `erp.py`, `AutomationsCard.jsx` (nouveau), `InvoicesPanel.jsx`, `DocumentPanel.jsx` |
| Limite de connexion | Après **5 essais ratés en 5 minutes** depuis la même adresse, la connexion est bloquée 5 minutes avec un message clair. Au-delà de 20 essais sur le même identifiant (toutes adresses confondues), il est aussi bloqué. Les échecs s'effacent tout seuls après 1 h. | `server.py`, `erp_indexes.py` |
| Barre à pousser P33 sur les plans | Nouvelle case **« Barre à pousser (P33) »** avec hauteur (42 po par défaut), centre à centre (33 po pour un P33, sinon automatique) et choix du vantail. La barre et ses deux pattes sont dessinées, avec la cote c/c. Elle apparaît en trait caché pour les mains inversées (MGR/MDR). | `erp_pdf_production.py`, `erp_routes_production_plans.py`, `ProductionPlansPanel.jsx`, `utils.js` |
| Push paddle sur les plans | La palette de relâche est maintenant dessinée de façon réaliste, comme une Adams Rite 4590 : un écusson sur le montant serrure, plus une palette horizontale avec la mention « POUSSER ». L'ancien dessin ressemblait à une barre panique. | `erp_pdf_production.py` |
| Dessin automatique | Les dessins P33 et palette apparaissent **automatiquement** quand la pièce est dans la liste de quincaillerie (P33-SA, ADAM-4590…), même si la case n'est pas cochée. Ajouter la pièce depuis la recherche Master coche aussi la case. L'assistante IA connaît la nouvelle case. | `erp_pdf_production.py`, `ProductionPlansPanel.jsx`, `erp_routes_assistant.py` |
| Erreurs mineures des plans | Le titre de la page couverture ne chevauche plus « DESSINS POUR PRODUCTION », et la mention « POUR APPROBATION » ne chevauche plus le slogan dans l'en-tête des pages. Les libellés longs du bloc « Verre & moulures » ne chevauchent plus leur valeur. Les cotes de hauteur (poignée, serrure, palette, levier…) ont chacune leur colonne au lieu de se superposer, et une même hauteur n'est plus cotée deux fois. Les fractions affichent « 36" » au lieu de « 35 1/1" ». | `erp_pdf_production.py` |
| Amélioration des plans | La page couverture affiche maintenant un **sommaire des portes** : repère, série, configuration, ouverture, main, quantité et fini. | `erp_pdf_production.py` |

## Bogues trouvés en testant (corrigés)

1. **Dates affichées un jour trop tôt au Québec.** Une facture datée du 31 octobre s'affichait « 30 oct. » dans l'ERP et sur la version imprimable envoyée aux clients. Le soir après 19 h, la date du jour proposée était déjà celle du lendemain. Ça touchait les factures, soumissions, dépenses, kilométrage, jobs, paiements et le récap TPS/TVQ. Les PDF générés par le serveur n'étaient pas touchés. → `utils.js` et 8 panneaux.
2. **Numérotation qui plante après une restauration.** Si le compteur de numéros est en retard sur les documents (par exemple une base restaurée depuis les sauvegardes JSON, qui n'incluent pas les compteurs), chaque nouvelle facture ou soumission donnait une erreur 500. Le compteur se réaligne maintenant tout seul. → `erp_helpers.py`
3. **Factures absentes des états de compte.** Une facture sans fiche client et sans courriel n'apparaissait nulle part dans les états de compte, et son montant manquait au « solde total dû ». → `erp_routes_statements.py`
4. **Suppression d'un client qui a des factures.** C'était permis, et la fiche disparaissait, avec son courriel et son adresse. C'est maintenant refusé, avec un message qui explique pourquoi. → `erp_routes_parties.py`
5. **Badge « Rappelé J+30 · 21 j retard »** qui débordait sur les boutons d'action dans la liste des factures. Le badge de retard n'apparaissait pas non plus pour les statuts « en retard » et « partiellement payée ». → `DocumentPanel.jsx`, `utils.js`
6. **Pixel Facebook chargé dans l'ERP.** Il envoyait à Meta l'adresse des pages internes. Il ne se charge plus que sur le site public. → `public/index.html`

## Deuxième série (12 novembre, soir)

| Demande | Ce qui a été fait | Fichiers |
|---|---|---|
| Barre à pousser en pointillé pour MDR / MGR | Vérifié et couvert par un test : en main inversée, la barre (et la palette) sont en trait caché, sur porte simple comme sur paire | `erp_pdf_production.py`, test |
| Retirer corridor, vestibule, intérieur, extérieur **des détails seulement** | Les mots ont été effacés des 24 dessins de détail qui les contenaient (48 mentions, vérifiées par lecture automatique après coup). La mention « (ouvrant intérieur/extérieur) » a aussi été retirée du pied de page des détails. L'élévation garde « VUE INTÉRIEUR ». | `backend/assets/production_details/ref/plan_*_md/mdr/mg/mgr.png` (24 images), `erp_pdf_production.py` |
| Sens d'ouverture comme sur un plan d'architecte | Sous chaque élévation : jambages, battant ouvert à 20° et arc pointillé, avec « Sens d'ouverture — MD ». MD/MG : la porte s'ouvre en s'éloignant de la vue. MDR/MGR : elle s'ouvre vers la vue. Une paire montre les deux battants. L'élévation est un peu réduite pour faire la place. | `erp_pdf_production.py` |
| Push paddle trop étroit | La palette est maintenant une plaque d'environ 4 po de haut sur 5 29/32 po (Adams Rite 4590), avec rainures. Les cotes de hauteur partent au-delà de la palette pour ne pas passer dessous. | `erp_pdf_production.py` |
| Sommaire de couverture « fondu » | Plus de rectangle blanc ni de bandeau marine : un voile blanc à bords progressifs, un en-tête en texte avec un filet et des lignes fines. | `erp_pdf_production.py` |

Tests : `backend/tests/test_ameliorations_2026_11.py` contient maintenant 10 tests, dont le PDF du devis de travaux, (sens d'ouverture pour les 4 mains, aucune mention intérieur/extérieur sur les détails, pointillé en main inversée).

## Troisième série : devis de travaux pour sous-traitant (12 novembre, soir)

**Nouvel onglet : Fabrication → Devis de travaux (sous-traitants).** Il est aussi dans le menu « Plus » sur cellulaire. Chaque devis est numéroté DT-AAAA-NNN et contient :
- le sous-traitant (choisi depuis une fiche fournisseur ou tapé à la main) ;
- le **lieu de l'intervention** : client (rempli depuis une fiche client), nom du lieu, adresse, contact et téléphone sur place, porte visée, accès, stationnement, horaires ;
- le **problème rapporté par le client**, mis en évidence en rouge, et le constat ou la cause probable ;
- les **travaux à effectuer**, en cases à cocher (on peut les réordonner et cocher « fait ») ;
- le matériel (fourni par Portech ou par le sous-traitant), les consignes (prêtes à l'emploi, modifiables) et la rémunération (forfait, taux horaire avec maximum d'heures, ou à confirmer ; on peut la masquer) ;
- jusqu'à 8 **photos**, réduites automatiquement et imprimées avec leur légende ;
- un bloc de signature (acceptation et fin des travaux), un lien vers une job et la référence du client ;
- des **notes internes**, jamais imprimées.

Actions possibles : PDF, envoi par courriel au sous-traitant (le statut passe à « envoyé »), duplication, changement rapide de statut, suppression.

Fichiers : `backend/erp_routes_work_orders.py` et `backend/erp_pdf_work_order.py` (nouveaux), `backend/erp.py`, `backend/erp_indexes.py`, `frontend/src/pages/erp/panels/WorkOrdersPanel.jsx` (nouveau), `frontend/src/pages/AdminErp.jsx`, `frontend/src/components/mobile/MobileTabBar.jsx`.

**Bogue trouvé en testant, et corrigé :** l'historique de **Composer courriel** plantait (erreur 500) dès qu'un courriel avait été envoyé ailleurs dans l'ERP (facture, relance, etc.). Le journal des courriels écrit dans la même collection avec un autre format. → `backend/erp_routes_compose.py`

## Tests ajoutés

`backend/tests/test_ameliorations_2026_11.py` : 6 tests qui tournent **sans serveur ni base de données**. Ils couvrent les fractions, la détection P33 et palette, les dessins, le sommaire de couverture et les cotes en double. Commande :

```
cd backend && python -m pytest tests/test_ameliorations_2026_11.py -q
```

## À savoir avant de déployer

- **Les relances partiront dès le lendemain matin à 8 h** pour toutes les factures envoyées, en retard de plus de 7 jours, avec un solde dû et un client qui a un courriel. Juste après le déploiement, ouvre **Factures → Envois automatiques** et vérifie la liste. Si tu veux attendre, désactive l'interrupteur.
- Fais un **redéploiement complet (rebuild)**. Les notes d'Emergent indiquent qu'un redéploiement sans reconstruction n'embarque pas le nouveau code.
- La variable `ERP_REMINDERS_PAUSED=true` sert maintenant d'arrêt d'urgence. Si elle existe dans ta configuration Emergent avec la valeur `true`, les relances restent bloquées : retire-la.
- `backend/backups/` est maintenant ignoré par Git, parce que ces fichiers contiennent des données et une clé privée. Les fichiers déjà enregistrés dans l'historique y restent ; voir le rapport.
