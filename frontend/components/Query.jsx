import {useState} from 'react';

function Query({onQuery}) {
    const [query, setQuery] = useState(''); 
    const handleInputChange = (e) => {
        setQuery(e.target.value);
    }

    const handleQuery = () => {
        if (query) {
            onQuery(query);
        }
    }

    return (
        <div>
            <input type="text" value={query} onChange={handleInputChange} />
            <button onClick={handleQuery}>Query</button>
        </div>
    )
}

export default Query
