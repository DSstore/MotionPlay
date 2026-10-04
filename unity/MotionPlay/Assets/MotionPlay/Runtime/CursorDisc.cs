using UnityEngine;

namespace MotionPlay.Unity
{
    /// <summary>Original geometric placeholder: a one-world-unit disc, generated locally without artwork.</summary>
    [DisallowMultipleComponent]
    [RequireComponent(typeof(SpriteRenderer))]
    public sealed class CursorDisc : MonoBehaviour
    {
        private Texture2D texture;
        private Sprite sprite;

        private void Awake()
        {
            const int size = 64;
            texture = new Texture2D(size, size, TextureFormat.RGBA32, false)
            { name = "MotionPlay cursor disc", filterMode = FilterMode.Bilinear, wrapMode = TextureWrapMode.Clamp };
            var pixels = new Color32[size * size];
            for (int y = 0; y < size; y++)
                for (int x = 0; x < size; x++)
                {
                    float dx = (x + 0.5f - size / 2f) / (size / 2f);
                    float dy = (y + 0.5f - size / 2f) / (size / 2f);
                    float radius = Mathf.Sqrt(dx * dx + dy * dy);
                    byte alpha = (byte)(255 * Mathf.Clamp01((1 - radius) * size / 2f));
                    pixels[y * size + x] = radius > 0.82f
                        ? new Color32(220, 255, 245, alpha) : new Color32(78, 221, 181, alpha);
                }
            texture.SetPixels32(pixels);
            texture.Apply(false);
            sprite = Sprite.Create(texture, new Rect(0, 0, size, size), new Vector2(0.5f, 0.5f), size,
                                   0, SpriteMeshType.FullRect);
            sprite.name = "MotionPlay cursor disc";
            GetComponent<SpriteRenderer>().sprite = sprite;
        }

        private void OnDestroy()
        {
            if (sprite != null) Destroy(sprite);
            if (texture != null) Destroy(texture);
        }
    }
}
