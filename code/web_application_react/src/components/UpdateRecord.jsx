import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

const API_BASE = "http://localhost:8010";

function UpdateRecord({ isLoggedIn }) {
  const [searchParams] = useSearchParams();
  const recordId = searchParams.get("id");

  const [address, setAddress] = useState("");
  const [landlordName, setLandlordName] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!isLoggedIn || !recordId) {
      setLoading(false);
      return;
    }

    async function fetchRecord() {
      try {
        const response = await fetch(`${API_BASE}/api/listings/${recordId}`, {
          credentials: "include",
        });
        if (!response.ok) {
          throw new Error(`Server responded with ${response.status}`);
        }
        const data = await response.json();
        setAddress(data.address);
        setLandlordName(data.landlordName);
      } catch (err) {
        console.error("Failed to load record:", err);
        setError("Failed to load record.");
      } finally {
        setLoading(false);
      }
    }

    fetchRecord();
  }, [isLoggedIn, recordId]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/api/listings/${recordId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ address, landlordName }),
      });

      if (!response.ok) {
        throw new Error(`Server responded with ${response.status}`);
      }

    
      navigate("/");
    } catch (err) {
      console.error("Failed to update listing:", err);
      setError("Failed to update listing. Please try again.");
    }
  };

  if (!isLoggedIn) {
    return (
      <div className="container mt-5 text-center">
        <div className="alert alert-warning">Login required.</div>
      </div>
    );
  }

  if (!recordId) {
    return (
      <div className="container mt-5 text-center">
        <div className="alert alert-danger">No record ID specified.</div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="container mt-5 text-center">
        <div className="alert alert-info">Loading record...</div>
      </div>
    );
  }

  return (
    <div className="container mt-5" style={{ maxWidth: "480px" }}>
      <div className="card shadow-sm">
        <div className="card-body">
          <h2 className="mb-4">Update Listing #{recordId}</h2>

          {error && <div className="alert alert-danger">{error}</div>}

          <form onSubmit={handleSubmit}>
            <div className="mb-3">
              <label htmlFor="address" className="form-label">Property Address</label>
              <input
                type="text"
                className="form-control"
                id="address"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                required
                autoFocus
              />
            </div>

            <div className="mb-3">
              <label htmlFor="landlordName" className="form-label">Landlord / Property Manager Name</label>
              <input
                type="text"
                className="form-control"
                id="landlordName"
                value={landlordName}
                onChange={(e) => setLandlordName(e.target.value)}
                required
              />
            </div>

            <button type="submit" className="btn btn-primary w-100">
              Save Changes
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default UpdateRecord;