import os
import shutil
import logging
import zipfile
import rarfile
import hashlib

# Configurer la journalisation pour le fichier et le terminal
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler('script.log'),
                        logging.StreamHandler()
                    ])

# Définir les répertoires source et cible
repertoire_source = 'pack/'
repertoire_cible = 'diamond_sword_trouve/'
repertoire_premade = 'premade/sword_'
repertoire_copie = 'pack_folder_sword/'

noms_fichiers_cibles = [
    'diamond_sword.png'
]

# Initialiser un ensemble pour stocker les hashes des images déjà copiées
hashes_images_copiees = set()


def calculer_hash_fichier(fichier):
    """Calculer le hash SHA-256 du fichier donné."""
    sha256 = hashlib.sha256()
    with open(fichier, 'rb') as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def compresser_dossier(dossier, zip_name):
    """Compresser le contenu du dossier en un fichier zip."""
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for racine, _, fichiers in os.walk(dossier):
            for fichier in fichiers:
                chemin_fichier = os.path.join(racine, fichier)
                arcname = os.path.relpath(chemin_fichier, dossier)
                zipf.write(chemin_fichier, arcname)
    logging.info(f'Compressé le dossier {dossier} en {zip_name}')


def copier_dossier_premade(cible, compteur, source_fichiers=None, repertoire_copie=None):
    dossier_temporaire = os.path.join(cible, str(compteur), f'sword_{compteur}')
    os.makedirs(dossier_temporaire, exist_ok=True)
    logging.info(f'Dossier temporaire créé : {dossier_temporaire}')

    if source_fichiers:
        for nom_fichier_cible, source_fichier in source_fichiers.items():
            # Déplacer et renommer le fichier cible en pack.png
            chemin_fichier_destination = os.path.join(dossier_temporaire, 'pack.png')
            shutil.copy(source_fichier, chemin_fichier_destination)
            logging.info(f'Rennomé {nom_fichier_cible} en pack.png dans {dossier_temporaire}')

            # Ajouter une autre copie de {nom_fichier_cible} dans \assets\minecraft\textures\items\
            chemin_fichier_assets = os.path.join(dossier_temporaire, 'assets', 'minecraft', 'textures', 'items')
            os.makedirs(chemin_fichier_assets, exist_ok=True)
            shutil.copy(source_fichier, os.path.join(chemin_fichier_assets, nom_fichier_cible))
            logging.info(f'Ajouté une copie de {nom_fichier_cible} dans {chemin_fichier_assets}')

    # Copier le contenu du dossier premade dans le dossier temporaire
    shutil.copytree(repertoire_premade, dossier_temporaire, dirs_exist_ok=True)
    logging.info(f'Copié le dossier premade vers {dossier_temporaire}')

    # Compresser le dossier temporaire en .zip
    nom_zip = os.path.join(cible, str(compteur), f'sword_{compteur}.zip')
    compresser_dossier(dossier_temporaire, nom_zip)

    # Copier le fichier zip dans le répertoire de copie
    if repertoire_copie:
        chemin_copie = os.path.join(repertoire_copie, f'sword_{compteur}.zip')
        shutil.copy(nom_zip, chemin_copie)
        logging.info(f'Copié {nom_zip} vers {chemin_copie}')

    # Supprimer le dossier temporaire après compression
    shutil.rmtree(dossier_temporaire)
    logging.info(f'Dossier temporaire supprimé : {dossier_temporaire}')


def extraire_et_copier(archive, noms_fichiers, cible, compteur):
    fichiers_extraits = {}
    for nom_fichier in noms_fichiers:
        try:
            for fichier in archive.namelist():
                if fichier.endswith(nom_fichier):
                    # Calculer le hash de l'image
                    with archive.open(fichier) as fichier_archive:
                        chemin_temporaire = os.path.join(cible, str(compteur), nom_fichier)
                        os.makedirs(os.path.dirname(chemin_temporaire), exist_ok=True)
                        with open(chemin_temporaire, 'wb') as fichier_temp:
                            shutil.copyfileobj(fichier_archive, fichier_temp)
                        hash_image = calculer_hash_fichier(chemin_temporaire)

                        # Vérifier si le hash de l'image a déjà été rencontré
                        if hash_image in hashes_images_copiees:
                            logging.info(f'Image {nom_fichier} ignorée (déjà copiée)')
                            os.remove(chemin_temporaire)
                            continue

                        # Ajouter le hash à l'ensemble des images copiées
                        hashes_images_copiees.add(hash_image)

                    fichiers_extraits[nom_fichier] = chemin_temporaire
                    logging.info(f'Fichier {nom_fichier} extrait de l\'archive vers {chemin_temporaire}')
                    break
            else:
                logging.warning(f'Fichier {nom_fichier} non trouvé dans l\'archive.')
        except KeyError:
            logging.warning(f'Fichier {nom_fichier} non trouvé dans l\'archive.')
    return fichiers_extraits


def traiter_archives(source, cible, compteur):
    try:
        for racine, _, fichiers in os.walk(source):
            for fichier in fichiers:
                chemin_complet = os.path.join(racine, fichier)
                if fichier.endswith('.zip'):
                    logging.debug(f'Ouverture de l\'archive ZIP : {fichier}')
                    with zipfile.ZipFile(chemin_complet, 'r') as archive_zip:
                        fichiers_extraits = extraire_et_copier(archive_zip, noms_fichiers_cibles, cible, compteur)
                        if fichiers_extraits:
                            copier_dossier_premade(cible, compteur, fichiers_extraits, repertoire_copie)
                            compteur += 1
                elif fichier.endswith('.rar'):
                    logging.debug(f'Ouverture de l\'archive RAR : {fichier}')
                    with rarfile.RarFile(chemin_complet) as archive_rar:
                        fichiers_extraits = extraire_et_copier(archive_rar, noms_fichiers_cibles, cible, compteur)
                        if fichiers_extraits:
                            copier_dossier_premade(cible, compteur, fichiers_extraits, repertoire_copie)
                            compteur += 1
    except Exception as e:
        logging.error(f'Une erreur est survenue dans traiter_archives: {e}')


def trouver_et_copier_arcs(source, cible):
    compteur = 1
    try:
        if not os.path.exists(source):
            logging.error(f'Le répertoire source n\'existe pas : {source}')
            return

        if not os.path.exists(cible):
            logging.debug(f'Le répertoire cible n\'existe pas, création : {cible}')
            os.makedirs(cible, exist_ok=True)

        fichiers_trouves_total = 0
        for racine, _, fichiers in os.walk(source):
            fichiers_trouves = {}
            for fichier in fichiers:
                chemin_complet = os.path.join(racine, fichier)

                if fichier in noms_fichiers_cibles:
                    # Calculer le hash de l'image
                    hash_image = calculer_hash_fichier(chemin_complet)

                    # Vérifier si le hash de l'image a déjà été rencontré
                    if hash_image in hashes_images_copiees:
                        logging.info(f'Image {fichier} ignorée (déjà copiée)')
                        continue

                    # Ajouter le hash à l'ensemble des images copiées
                    hashes_images_copiees.add(hash_image)

                    fichiers_trouves[fichier] = chemin_complet
                    logging.info(f'Fichier {fichier} trouvé dans {racine}')

            if fichiers_trouves:
                copier_dossier_premade(cible, compteur, fichiers_trouves, repertoire_copie)
                fichiers_trouves_total += len(fichiers_trouves)
                compteur += 1

        traiter_archives(source, cible, compteur)

        # Afficher les informations finales dans le terminal
        logging.info(f'Traitement terminé.')
        logging.info(f'Nombre total de fichiers trouvés et copiés : {fichiers_trouves_total}')

    except Exception as e:
        logging.error(f'Une erreur est survenue dans trouver_et_copier_arcs: {e}')


if __name__ == "__main__":
    logging.debug('Début du script')
    trouver_et_copier_arcs(repertoire_source, repertoire_cible)
    logging.debug('Fin du script')
