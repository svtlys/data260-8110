import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useDispatch } from "react-redux";
import { updateListing } from "../store/listingsSlice";

const API_BASE = "http://localhost:8010/api";

function UpdateRecord({ isLoggedIn }) {
  const [searchParams] = useSearchParams();
  const recordId = searchParams.get("id");

  const [address, setAddress] = useState("");
  const [landlordId, setLandlordId] = useState("");
  const [listingCode, setListingCode] = useState("");
  const [availableUnits, setAvailableUnits] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const dispatch = useDispatch();
  const navigate = useNavigate();

  useEffect(() => {
    if (!isLoggedIn || !recordId) {
      setLoading(false);
      return;
    }

    async function fetchRecord() {
      try {
        const response = await fetch(`${API_BASE}/listings/${recordId}`, {
          credentials: "include",
        });
        if (!response.ok) {
          throw new Error(`Server responded with ${response.status}`);
        }
        const data = await response.json();
        setAddress(data.address);
        setLandlordId(data.landlord_id ?? "");
        setListingCode(data.listing_code ?? "");
        setAvailableUnits(data.available_units);
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

    const payload = {
      id: recordId,
      address,
      landlord_id: landlordId ? parseInt(landlordId, 10) : null,
      listing_code: listingCode || null,
      available_units: availableUnits,
    };

    const result = await dispatch(updateListing(payload));

    if (updateListing.fulfilled.match(result)) {
      navigate("/");
    } else {
      setError(result.payload || "Failed to update listing.");
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
          <h2 className="mb-4 text-dark">Update Listing #{recordId}</h2>

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
              <label htmlFor="landlordId" className="form-label">Landlord ID (optional)</label>
              <input
                type="number"
                className="form-control"
                id="landlordId"
                value={landlordId}
                onChange={(e) => setLandlordId(e.target.value)}
              />
            </div>

            <div className="mb-3">
              <label htmlFor="listingCode" className="form-label">Listing Code (optional, format XX-NNNN)</label>
              <input
                type="text"
                className="form-control"
                id="listingCode"
                value={listingCode}
                onChange={(e) => setListingCode(e.target.value)}
              />
            </div>

            <div className="mb-3">
              <label htmlFor="availableUnits" className="form-label">Available Units</label>
              <input
                type="number"
                className="form-control"
                id="availableUnits"
                value={availableUnits}
                onChange={(e) => setAvailableUnits(parseInt(e.target.value, 10) || 0)}
                min="0"
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