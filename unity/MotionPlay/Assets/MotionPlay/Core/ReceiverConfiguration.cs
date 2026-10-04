using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace MotionPlay.Networking
{
    /// <summary>Nonsecret listener options; only the selected numeric .env keys are used.</summary>
    public sealed class ReceiverConfiguration
    {
        public int Port { get; }
        public double TimeoutSeconds { get; }

        public ReceiverConfiguration(int port = 5005, double timeoutSeconds = 0.5)
        {
            if (port < 1024 || port > 65535) throw new ArgumentException("CV_TO_UNITY_PORT must be 1024..65535.");
            if (double.IsNaN(timeoutSeconds) || double.IsInfinity(timeoutSeconds) || timeoutSeconds <= 0)
                throw new ArgumentException("UNITY_RECEIVE_TIMEOUT must be finite and positive.");
            Port = port; TimeoutSeconds = timeoutSeconds;
        }

        /// <summary>Defaults, optional .env file, then process environment; no global mutation.</summary>
        public static ReceiverConfiguration Load(string envFile, Func<string, string> environment)
        {
            var values = new Dictionary<string, string>
            {
                ["CV_TO_UNITY_PORT"] = "5005", ["UNITY_TO_PYTHON_PORT"] = "5006",
                ["UNITY_RECEIVE_TIMEOUT"] = "0.5"
            };
            if (!string.IsNullOrEmpty(envFile) && File.Exists(envFile))
            {
                foreach (string raw in File.ReadLines(envFile, new UTF8Encoding(false, true)))
                {
                    string line = raw.Trim();
                    if (line.StartsWith("export ", StringComparison.Ordinal)) line = line.Substring(7).TrimStart();
                    int equals = line.IndexOf('=');
                    if (equals < 0) continue;
                    string key = line.Substring(0, equals).Trim();
                    if (!values.ContainsKey(key)) continue;
                    string value = line.Substring(equals + 1).Trim();
                    if (value.StartsWith("\"") || value.StartsWith("'"))
                    {
                        int end = value.IndexOf(value[0], 1);
                        if (end < 0 || (value.Substring(end + 1).Trim().Length > 0 &&
                            !value.Substring(end + 1).Trim().StartsWith("#")))
                            throw new ArgumentException(key + " has invalid quoting.");
                        value = value.Substring(1, end - 1);
                    }
                    else
                    {
                        int comment = value.IndexOf(" #", StringComparison.Ordinal);
                        if (comment >= 0) value = value.Substring(0, comment).TrimEnd();
                    }
                    values[key] = value.Trim();
                }
            }
            foreach (string key in new List<string>(values.Keys))
            {
                string value = environment(key);
                if (value != null) values[key] = value.Trim();
            }
            int port = PortValue(values, "CV_TO_UNITY_PORT");
            if (port == PortValue(values, "UNITY_TO_PYTHON_PORT"))
                throw new ArgumentException("CV_TO_UNITY_PORT and UNITY_TO_PYTHON_PORT must differ.");
            if (!double.TryParse(values["UNITY_RECEIVE_TIMEOUT"], NumberStyles.Float,
                CultureInfo.InvariantCulture, out double timeout))
                throw new ArgumentException("UNITY_RECEIVE_TIMEOUT must be finite and positive.");
            return new ReceiverConfiguration(port, timeout);
        }

        private static int PortValue(Dictionary<string, string> values, string key)
        {
            if (!int.TryParse(values[key], NumberStyles.Integer, CultureInfo.InvariantCulture, out int port)
                || port < 1024 || port > 65535)
                throw new ArgumentException(key + " must be an integer from 1024 to 65535.");
            return port;
        }
    }
}
