using System.IO;
using MotionPlay.Unity;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace MotionPlay.Editor
{
    public static class HandCursorSceneSetup
    {
        [MenuItem("MotionPlay/Create Hand Cursor Test Scene")]
        public static void CreateScene()
        {
            if (Application.isPlaying || !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            const string path = "Assets/MotionPlay/Scenes/HandCursorTest.unity";
            if (File.Exists(path) && !EditorUtility.DisplayDialog("MotionPlay", "Replace the existing cursor test scene?", "Replace", "Cancel")) return;
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
            EditorSceneManager.SaveScene(scene, path);
            AssetDatabase.Refresh();
            Selection.activeGameObject = cursorObject;
            Debug.Log("MotionPlay hand cursor scene created. Press Play, then start Python tracking. Verify the proof of concept before gameplay.");
        }
    }
}
