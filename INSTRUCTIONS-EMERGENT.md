# Instructions pour l'agent Emergent — à copier-coller tel quel

Bonjour. Ce ZIP contient des fichiers **déjà modifiés et testés**. Ils ont été écrits hors d'Emergent. Merci de les appliquer **exactement tels quels**.

1. Décompresse le ZIP. Chaque fichier a son chemin relatif à la racine du projet (`/app`). Par exemple, `backend/erp_pdf_production.py` va dans `/app/backend/erp_pdf_production.py`.
2. **Remplace** chaque fichier existant par celui du ZIP, et **ajoute** les fichiers nouveaux. Les images PNG de `backend/assets/production_details/ref/` sont aussi à remplacer : ce sont des fichiers binaires, copie-les sans conversion.
3. **Ne modifie, ne régénère et ne reformate aucun autre fichier**, et ne réécris pas le contenu de ces fichiers. Aucune nouvelle dépendance n'est requise.
4. Redémarre le backend et le frontend : `sudo supervisorctl restart backend frontend`.
5. Lance les tests hors-ligne : `cd /app/backend && python -m pytest tests/test_ameliorations_2026_11.py -q`. Résultat attendu : **10 passed**.
6. Vérifie dans la prévisualisation :
   - **Factures** : un encadré « Envois automatiques » apparaît en haut ;
   - **Fabrication → Dessin de production de porte** : une case « Barre à pousser (P33) » existe ;
   - **Plans** : un PDF de plan montre le symbole « Sens d'ouverture » sous chaque élévation ;
   - **Fabrication → Devis de travaux (sous-traitants)** : l'onglet s'ouvre et un devis de test peut être créé, puis ouvert en PDF.
7. Déploie avec une **reconstruction complète (rebuild)**, pas seulement un redémarrage.

Les fichiers concernés et la raison de chaque changement sont listés dans `CHANGEMENTS-2026-11.md`, à la racine du ZIP.
