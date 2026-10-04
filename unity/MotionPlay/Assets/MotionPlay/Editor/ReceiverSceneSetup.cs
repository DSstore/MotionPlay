using System.IO;
using MotionPlay.Unity;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace MotionPlay.Editor
{
    /// <summary>Create the reproducible diagnostic scene through supported Unity APIs.</summary>
    public static class ReceiverSceneSetup
    {
        [MenuItem("MotionPlay/Create Receiver Test Scene")]
        public static void CreateScene()
        {
            if (Application.isPlaying || !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            const string path = "Assets/MotionPlay/Scenes/ReceiverTest.unity";
            if (File.Exists(path) && !EditorUtility.DisplayDialog("MotionPlay", "Replace the existing receiver test scene?", "Replace", "Cancel")) return;
            Directory.CreateDirectory("Assets/MotionPlay/Scenes");
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var cameraObject = new GameObject("Main Camera");
            cameraObject.tag = "MainCamera";
            var camera = cameraObject.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.08f, 0.14f, 0.12f);
            camera.orthographic = true;
            cameraObject.transform.position = new Vector3(0, 0, -10);
            var receiverObject = new GameObject("MotionPlay Receiver");
            receiverObject.AddComponent<UdpReceiver>();
            receiverObject.AddComponent<ReceiverDebugPanel>();
            EditorSceneManager.SaveScene(scene, path);
            AssetDatabase.Refresh();
            Selection.activeGameObject = receiverObject;
            Debug.Log("MotionPlay receiver test scene created. Press Play, then start the Python CV engine.");
        }
    }
}
