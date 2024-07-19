/****************** model button logic ******************/

var modelButton = document.getElementById("modelButton");
var modelName = "XYZ";

function changeModel() {
    var modelText = document.getElementById("model-text");
    if (modelName === "XYZ") {
        modelName = "CPRG";
        modelText.innerHTML = "Model CPRG";
    } else if (modelName === "CPRG") {
        modelName = "XYZ";
        modelText.innerHTML = "Model XYZ";
    }
    recalculate();
}

modelButton.addEventListener("click", changeModel);

/****************** duration button logic ******************/

var durationButton = document.getElementById("durationButton");
var duration = 0;

function changeDuration() {
    var durationText = document.getElementById("duration-text");
    var newDuration = prompt("Enter new duration in days:");
    if (newDuration !== null && !isNaN(newDuration) && newDuration > 0) {
        duration = newDuration;
        durationText.innerHTML = duration;
    } else {
        alert("Please enter a valid duration.");
    }
    recalculate();
}

durationButton.addEventListener("click", changeDuration);

function recalculate() {
    var costPerDay = modelName === "XYZ" ? 100 : 213;
    var totalCost = costPerDay * duration;
    document.getElementById("calculated-cost").innerHTML = totalCost.toFixed(2);
}
