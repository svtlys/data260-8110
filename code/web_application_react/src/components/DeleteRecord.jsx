import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

const API_BASE = "http://localhost:8010";

function DeleteRecord({ isLoggedIn }) {
  const [searchParams] = useSearchParams();
  const recordId = searchParams.get("id");

  const [record, setRecord] = useState(null);
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
    try {
      const response = await fetch(`${API_BASE}/api/listings/${recordId}`, {
        method: "DELETE",
        credentials: "include",
      });

      if (!response.ok) {
        throw new Error(`Server responded with ${response.status}`);
      }

      // Removed from MySQL -- redirect to home to see the updated list
      navigate("/");
    } catch (err) {
      console.error("Failed to delete listing:", err);
      setError("Failed to delete listing. Please try again.");
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
          <h2 className="mb-4">Delete Listing #{recordId}</h2>

          {error && <div className="alert alert-danger">{error}</div>}

          {record && (
            <p className="mb-4">
              Are you sure you want to delete <strong>{record.address}</strong>
              {" "}(listed by {record.landlordName})?
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