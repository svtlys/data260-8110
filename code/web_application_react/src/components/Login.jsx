import { useState } from "react";
import { useNavigate } from "react-router-dom";

const API_BASE = "http://localhost:8010";

function Login({ onLoginSuccess }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/api/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        setError("Invalid email or password.");
        return;
      }

      onLoginSuccess();
      navigate("/");
    } catch (err) {
      console.error("Login failed:", err);
      setError("Something went wrong. Please try again.");
    }
  };

  return (
    <div className="container mt-5" style={{ maxWidth: "420px" }}>
      <div className="card shadow-sm">
        <div className="card-body">
          <h2 className="text-center mb-4">Log In</h2>

          {error && (
            <div className="alert alert-danger" role="alert">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="mb-3">
              <label htmlFor="email" className="form-label">Email</label>
              <input
                type="email"
                className="form-control"
                id="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </div>

            <div className="mb-3">
              <label htmlFor="password" className="form-label">Password</label>
              <input
                type="password"
                className="form-control"
                id="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>

            <button type="submit" className="btn btn-primary w-100">
              Log In
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default Login;
