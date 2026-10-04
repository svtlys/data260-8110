import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useDispatch } from "react-redux";
import { deleteListing } from "../store/listingsSlice";

const API_BASE = "http://localhost:8010/api";

function DeleteRecord({ isLoggedIn }) {
  const [searchParams] = useSearchParams();
  const recordId = searchParams.get("id");

  const [record, setRecord] = useState(null);
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
        setRecord(data);
      } catch (err) {
        console.error("Failed to load record:", err);
        setError("Failed to load record.");
      } finally {
        setLoading(false);
      }
    }

    fetchRecord();
  }, [isLoggedIn, recordId]);

  const handleDelete = async () => {
    setError(null);
    const result = await dispatch(deleteListing(recordId));

    if (deleteListing.fulfilled.match(result)) {
      navigate("/");
    } else {
      setError(result.payload || "Failed to delete listing.");
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
        <div className="card-body text-center">
          <h2 className="mb-4 text-dark">Delete Listing #{recordId}</h2>

          {error && <div className="alert alert-danger">{error}</div>}

          {record && (
            <p className="mb-4">
              Are you sure you want to delete <strong>{record.address}</strong>
              {record.listing_code ? ` (${record.listing_code})` : ""}?
            </p>
          )}

          <button onClick={handleDelete} className="btn btn-danger">
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

export default DeleteRecord;