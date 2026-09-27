import { useState } from "react";
import { useNavigate } from "react-router-dom";

const API_BASE = "http://localhost:8010";

function CreateRecord({ isLoggedIn }) {
  const [address, setAddress] = useState("");
  const [landlordName, setLandlordName] = useState("");
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/api/listings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ address, landlordName }),
      });

      if (!response.ok) {
        throw new Error(`Server responded with ${response.status}`);
      }

      navigate("/");
    } catch (err) {
      console.error("Failed to create listing:", err);
      setError("Failed to add listing. Please try again.");
    }
  };

  if (!isLoggedIn) {
    return (
      <div className="container mt-5 text-center">
        <div className="alert alert-warning">Login required.</div>
      </div>
    );
  }

  return (
    <div className="container mt-5" style={{ maxWidth: "480px" }}>
      <div className="card shadow-sm">
        <div className="card-body">
          <h2 className="mb-4">Add Rental Listing</h2>

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
                placeholder="e.g. 123 Main St, San Jose, CA"
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
                placeholder="e.g. Jane Smith Property Management"
                required
              />
            </div>

            <button type="submit" className="btn btn-primary w-100">
              Add Listing
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default CreateRecord;