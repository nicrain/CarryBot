import pyrealsense2 as rs
import time

def main():
    # 1. Création du pipeline (le gestionnaire de flux de données)
    pipeline = rs.pipeline()
    config = rs.config()

    # 2. Configuration du flux
    # On demande le flux de profondeur (Depth)
    # Résolution : 640x480
    # Format : Z16 (entier 16 bits, standard pour la profondeur)
    # Fréquence : 30 images par seconde (fps)
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)

    try:
        print("--- Démarrage de CarryBot Vision ---")
        print("Tentative de connexion à la caméra Intel RealSense...")
        
        # 3. Démarrage de la caméra
        pipeline.start(config)
        print("Connexion réussie ! Lecture du flux en cours...")
        print("(Appuyez sur Ctrl+C pour arrêter le programme)\n")

        while True:
            # 4. Attendre la prochaine image (bloquant)
            frames = pipeline.wait_for_frames()
            
            # Récupérer l'image de profondeur
            depth_frame = frames.get_depth_frame()

            # Vérification de sécurité : si l'image est vide, on passe
            if not depth_frame:
                continue

            # 5. Mesure de la distance
            # On prend le pixel au centre de l'image (320, 240)
            width = depth_frame.get_width()
            height = depth_frame.get_height()
            
            # get_distance retourne la valeur en MÈTRES
            dist = depth_frame.get_distance(width // 2, height // 2)

            # 6. Affichage du résultat
            # Si la distance est 0.000, cela signifie souvent "trop près" ou "trop loin" (hors de portée)
            if dist == 0:
                print("Distance au centre : Hors de portée (ou trop près)")
            else:
                print(f"Distance au centre : {dist:.3f} mètres")

            # Petite pause pour rendre l'affichage lisible
            time.sleep(0.1)

    except KeyboardInterrupt:
        # Gère l'arrêt via Ctrl+C
        print("\nArrêt manuel détecté.")

    except Exception as e:
        # Gère les erreurs imprévues (câble débranché, etc.)
        print(f"\nUne erreur est survenue : {e}")

    finally:
        # 7. Nettoyage essentiel
        # Il est très important d'arrêter le pipeline pour libérer la caméra
        # Sinon, vous devrez débrancher/rebrancher l'USB pour la réutiliser
        print("Fermeture du flux vidéo et libération des ressources...")
        try:
            pipeline.stop()
        except:
            pass
        print("Terminé.")

if __name__ == "__main__":
    main()
