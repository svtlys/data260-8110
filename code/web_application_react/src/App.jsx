import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route, Link, useNavigate } from "react-router-dom";

import Login from "./components/Login";
import Home from "./components/Home";
import CreateRecord from "./components/CreateRecord";
import UpdateRecord from "./components/UpdateRecord";
import DeleteRecord from "./components/DeleteRecord";
import { Provider } from "react-redux";
import { store } from "./store/store";

const API_BASE = "http://localhost:8010";

function NavBar({ isLoggedIn, onLogout }) {
  return (
    <nav className="navbar navbar-dark" style={{ backgroundColor: "#3EB489" }}>
      <div className="container">
        <Link className="navbar-brand" to="/">Rental Housing Listings</Link>
        <div>
          {isLoggedIn ? (
            <button className="btn btn-outline-light btn-sm" onClick={onLogout}>
              Log Out
            </button>
          ) : (
            <Link className="btn btn-outline-light btn-sm" to="/login">
              Log In
            </Link>
          )}
        </div>
      </div>
    </nav>
  );
}

function AppRoutes({ isLoggedIn, setIsLoggedIn, onLogout }) {
  const navigate = useNavigate();

  return (
    <>
      <NavBar isLoggedIn={isLoggedIn} onLogout={onLogout} />
      <Routes>
        <Route path="/" element={<Home isLoggedIn={isLoggedIn} />} />
        <Route
          path="/login"
          element={
            <Login
              onLoginSuccess={() => {
                setIsLoggedIn(true);
                navigate("/");
              }}
            />
          }
        />
        <Route path="/create" element={<CreateRecord isLoggedIn={isLoggedIn} />} />
        <Route path="/update" element={<UpdateRecord isLoggedIn={isLoggedIn} />} />
        <Route path="/delete" element={<DeleteRecord isLoggedIn={isLoggedIn} />} />
      </Routes>
    </>
  );
}

function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    async function checkSession() {
      try {
        const response = await fetch(`${API_BASE}/api/me`, {
          credentials: "include",
        });
        setIsLoggedIn(response.ok);
      } catch (err) {
        setIsLoggedIn(false);
      } finally {
        setCheckingSession(false);
      }
    }
    checkSession();
  }, []);

  const handleLogout = async () => {
    try {
      await fetch(`${API_BASE}/api/logout`, {
        method: "POST",
        credentials: "include",
      });
    } catch (err) {
      console.error("Logout request failed:", err);
    } finally {
      setIsLoggedIn(false);
    }
  };

  if (checkingSession) {
    return <div className="container mt-5 text-center">Loading...</div>;
  }

  return (
    <Provider store={store}>
      <BrowserRouter>
        <AppRoutes
          isLoggedIn={isLoggedIn}
          setIsLoggedIn={setIsLoggedIn}
          onLogout={handleLogout}
        />
      </BrowserRouter>
    </Provider>
  );
}

export default App;