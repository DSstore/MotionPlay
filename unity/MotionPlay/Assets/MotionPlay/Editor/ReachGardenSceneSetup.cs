using System.IO;
using MotionPlay.Unity;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace MotionPlay.Editor
{
    public static class ReachGardenSceneSetup
    {
        [MenuItem("MotionPlay/Create Reach Garden Scene")]
        public static void CreateScene()
        {
            if (Application.isPlaying || !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            const string path = "Assets/MotionPlay/Scenes/ReachGarden.unity";
            if (File.Exists(path) && !EditorUtility.DisplayDialog("MotionPlay", "Replace the existing Reach Garden scene?", "Replace", "Cancel")) return;
            Directory.CreateDirectory("Assets/MotionPlay/Scenes");
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var cameraObject = new GameObject("Main Camera");
            cameraObject.tag = "MainCamera";
            var camera = cameraObject.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.08f, 0.14f, 0.12f);
            camera.orthographic = true;
            camera.orthographicSize = 3;
            cameraObject.transform.position = new Vector3(0, 0, -10);
            var receiverObject = new GameObject("MotionPlay Receiver");
            var receiver = receiverObject.AddComponent<UdpReceiver>();
            var diagnostics = receiverObject.AddComponent<ReceiverDebugPanel>();
            diagnostics.SetExpanded(false);
            var cursorObject = new GameObject("Hand Cursor");
            var renderer = cursorObject.AddComponent<SpriteRenderer>();
            renderer.enabled = false;
            renderer.sortingOrder = 100;
            cursorObject.AddComponent<CursorDisc>();
            var cursor = cursorObject.AddComponent<HandCursorController>();
            cursor.Configure(receiver, camera);
            cursorObject.AddComponent<HandCursorStatusPanel>();
            var gardenObject = new GameObject("Reach Garden");
            var garden = gardenObject.AddComponent<ReachGardenController>();
            garden.Configure(cursor, camera);
            EditorSceneManager.SaveScene(scene, path);
            AssetDatabase.Refresh();
            Selection.activeGameObject = gardenObject;
            Debug.Log("MotionPlay Reach Garden scene created. Press Play, then start Python tracking.");
        }
    }
}
